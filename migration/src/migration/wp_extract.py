"""
wp_extract.py — WordPress XML → SQLite + HTML 캐시 추출 모듈 (Phase 3)

역할:
  1. WP XML export를 파싱하여 post 메타데이터·원문 HTML·SEO·내부 링크를 추출
  2. migration/state.db의 posts 테이블에 INSERT (중복 시 SKIP)
  3. output-storage/migration/<slug>/reference/wp_original.html 생성
  4. 추출 보고서 및 소스 노트 체크리스트 Markdown 생성

CLI:
  python -m migration extract --xml <path>   # 추출 실행
  python -m migration extract --report        # 보고서만 재생성
  python -m migration sources-status          # migration-sources/ 진척 표
"""

import sqlite3
import os
import re
import json
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from lxml import etree
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# 상수 / 설정
# ─────────────────────────────────────────────

WP_BASE_URL = os.getenv("WP_BASE_URL", "https://youngkuklaw.com")
WP_EXPORT_PATH = os.getenv("WP_EXPORT_PATH", "./legacy-source/wordpress-export/youngkuklaw.WordPress.xml")

# lxml namespaces
NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "wp": "http://wordpress.org/export/1.2/",
    "excerpt": "http://wordpress.org/export/1.2/excerpt/",
}

# 카테고리 슬러그 매핑 (WP 원본 → 새로운 슬러그, 4.8절)
CATEGORY_SLUG_MAP: dict[str, str] = {
    "english-contract-law":  "contract-law",
    "english-tort-law":      "tort-law",
    "english-public-law":    "public-law",
    "english-criminal-law":  "criminal-law",
    "english-equity-law":    "equity-law",
    "english-land-law":      "land-law",
    "english-law":           "english-law",
    "case-law":              "case-law",
    "contract-case-law":     "contract-law-cases",
    "tort-case-law":         "tort-law-cases",
    "public-case-law":       "public-law-cases",
    "criminal-case-law":     "criminal-law-cases",
    "equity-case-law":       "equity-law-cases",
    "land-case-law":         "land-law-cases",
}

# Yoast / Rank Math SEO 메타 키
SEO_META_KEYS_YOAST = {
    "_yoast_wpseo_focuskw":           "focus_keyphrase",
    "_yoast_wpseo_metadesc":          "meta_description",
    "_yoast_wpseo_opengraph-title":   "og_title",
    "_yoast_wpseo_opengraph-description": "og_description",
    "_yoast_wpseo_opengraph-image":   "og_image",
    "_yoast_wpseo_title":             "seo_title",
}
SEO_META_KEYS_RANKMATH = {
    "rank_math_focus_keyword":        "focus_keyphrase",
    "rank_math_description":          "meta_description",
    "rank_math_og_title":             "og_title",
    "rank_math_og_description":       "og_description",
    "rank_math_og_image":             "og_image",
    "rank_math_seo_score":            "seo_score",
}


# ─────────────────────────────────────────────
# 유틸리티 함수
# ─────────────────────────────────────────────

def _text(el, xpath: str, ns: dict = NS) -> str:
    """xpath 결과의 첫 텍스트. 없으면 빈 문자열."""
    results = el.xpath(xpath, namespaces=ns)
    if not results:
        return ""
    r = results[0]
    return (r.text or "").strip() if hasattr(r, "text") else str(r).strip()


def _cdata(el, xpath: str, ns: dict = NS) -> str:
    """CDATA 섹션 포함 텍스트 추출."""
    results = el.xpath(xpath, namespaces=ns)
    if not results:
        return ""
    r = results[0]
    if hasattr(r, "text"):
        return (r.text or "").strip()
    return str(r).strip()


def _parse_wp_date(date_str: str) -> Optional[str]:
    """WordPress 발행일 → ISO8601 UTC. 실패 시 None."""
    if not date_str or date_str == "0000-00-00 00:00:00":
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return date_str  # 파싱 실패 시 원본 반환


# ─────────────────────────────────────────────
# 내부 링크 추출
# ─────────────────────────────────────────────

def extract_internal_links(html_str: str, base_url: str = WP_BASE_URL) -> list[str]:
    """HTML에서 내부 링크(href) 추출. slug 형태로 정규화 (소문자)."""
    if not html_str:
        return []
    soup = BeautifulSoup(html_str, "lxml")
    links = []
    parsed_base = urlparse(base_url)
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        parsed = urlparse(href)
        # 동일 도메인 or 상대경로
        if parsed.netloc in ("", parsed_base.netloc):
            path = parsed.path.strip("/").lower()  # 소문자 정규화
            if path and not path.startswith(("wp-", "feed", "?", "#")):
                links.append(path)
    return list(dict.fromkeys(links))  # 중복 제거, 순서 유지


# ─────────────────────────────────────────────
# SEO 메타 추출
# ─────────────────────────────────────────────

def extract_seo_meta(postmeta_list: list[etree._Element]) -> dict:
    """wp:postmeta 요소 리스트에서 Yoast/Rank Math SEO 메타 추출."""
    seo: dict[str, str] = {}
    for pm in postmeta_list:
        key = _text(pm, "wp:meta_key")
        val = _cdata(pm, "wp:meta_value")
        if key in SEO_META_KEYS_YOAST:
            field = SEO_META_KEYS_YOAST[key]
            if val:
                seo[field] = val
        elif key in SEO_META_KEYS_RANKMATH:
            field = SEO_META_KEYS_RANKMATH[key]
            if val:
                seo[field] = val
    return seo


# ─────────────────────────────────────────────
# 단일 <item> 파싱
# ─────────────────────────────────────────────

def parse_post(item_el: etree._Element) -> Optional[dict]:
    """
    <item> 요소 파싱 → dict or None (publish 상태 post 아니면 None).
    """
    post_type = _text(item_el, "wp:post_type")
    status = _text(item_el, "wp:status")

    if post_type != "post" or status != "publish":
        return None

    wp_id_str = _text(item_el, "wp:post_id")
    wp_id = int(wp_id_str) if wp_id_str.isdigit() else None
    if not wp_id:
        return None

    wp_slug = _text(item_el, "wp:post_name")
    title = _cdata(item_el, "title")
    # content:encoded
    content_encoded = item_el.xpath("content:encoded", namespaces=NS)
    html_content = ""
    if content_encoded:
        ce = content_encoded[0]
        html_content = (ce.text or "").strip()

    wp_url = _text(item_el, "link")
    pub_date_raw = _text(item_el, "wp:post_date_gmt")
    pub_date = _parse_wp_date(pub_date_raw)
    modified_date_raw = _text(item_el, "wp:post_modified_gmt")
    modified_date = _parse_wp_date(modified_date_raw)

    # 카테고리
    categories = []
    for cat_el in item_el.xpath("category[@domain='category']"):
        nicename = cat_el.get("nicename", "")
        if nicename:
            categories.append(CATEGORY_SLUG_MAP.get(nicename, nicename))
    wp_category = ",".join(categories) if categories else "uncategorized"

    # wp:postmeta 목록
    postmeta_list = item_el.xpath("wp:postmeta", namespaces=NS)
    seo = extract_seo_meta(postmeta_list)

    # 내부 링크
    internal_links = extract_internal_links(html_content)

    # 첨부 이미지 URL (본문 내 img src)
    soup = BeautifulSoup(html_content, "lxml") if html_content else None
    image_urls = []
    if soup:
        for img in soup.find_all("img", src=True):
            image_urls.append(img["src"])

    return {
        "id": wp_id,
        "wp_slug": wp_slug,
        "wp_url": wp_url,
        "wp_title_ko": title,
        "wp_category": wp_category,
        "wp_pub_date": pub_date or "",
        "wp_modified_date": modified_date,
        "html_content": html_content,
        "wp_seo": seo,
        "internal_links": internal_links,
        "image_urls": image_urls,
    }


# ─────────────────────────────────────────────
# DB 조작
# ─────────────────────────────────────────────

def _get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_post(conn: sqlite3.Connection, post: dict, html_path: str) -> bool:
    """DB에 post 삽입. 이미 존재하면 skip (False 반환)."""
    existing = conn.execute("SELECT id FROM posts WHERE id = ?", (post["id"],)).fetchone()
    if existing:
        return False

    conn.execute(
        """
        INSERT INTO posts (
            id, wp_slug, wp_url, wp_title_ko, wp_category,
            wp_pub_date, wp_modified_date, wp_html_path, wp_seo,
            status, sources
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            post["id"],
            post["wp_slug"],
            post["wp_url"],
            post["wp_title_ko"],
            post["wp_category"],
            post["wp_pub_date"],
            post["wp_modified_date"],
            html_path,
            json.dumps(post["wp_seo"], ensure_ascii=False),
            json.dumps(
                {
                    "internal_links": post["internal_links"],
                    "image_urls": post["image_urls"],
                    "notes_path": None,
                    "pdf_paths": [],
                },
                ensure_ascii=False,
            ),
        ),
    )
    return True


# ─────────────────────────────────────────────
# HTML 캐시 저장
# ─────────────────────────────────────────────

def _save_html_cache(post: dict, output_dir: str) -> str:
    """wp_original.html을 output-storage/migration/<slug>/reference/ 에 저장."""
    slug = post["wp_slug"]
    ref_dir = Path(output_dir) / "migration" / slug / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)
    html_path = ref_dir / "wp_original.html"

    # 간단한 HTML 래핑 (원문 콘텐츠 보존)
    wrapped = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <title>{post['wp_title_ko']} — WP Original (참조용)</title>
  <meta name="wp-slug" content="{slug}">
  <meta name="wp-pub-date" content="{post['wp_pub_date']}">
  <meta name="wp-category" content="{post['wp_category']}">
  <style>
    body {{ font-family: sans-serif; max-width: 900px; margin: 2rem auto; padding: 1rem; }}
    .meta {{ background: #f5f5f5; padding: 1rem; border-radius: 4px; margin-bottom: 2rem; font-size: 0.85rem; }}
    .content {{ line-height: 1.8; }}
  </style>
</head>
<body>
  <div class="meta">
    <strong>제목:</strong> {post['wp_title_ko']}<br>
    <strong>슬러그:</strong> {slug}<br>
    <strong>카테고리:</strong> {post['wp_category']}<br>
    <strong>발행일:</strong> {post['wp_pub_date']}<br>
    <strong>내부 링크 수:</strong> {len(post['internal_links'])}<br>
    <em>⚠ 이 파일은 참조 전용입니다. 본문 내용은 마이그레이션에 그대로 사용하지 않습니다.</em>
  </div>
  <div class="content">
{post['html_content']}
  </div>
</body>
</html>"""

    html_path.write_text(wrapped, encoding="utf-8")
    return str(html_path)


# ─────────────────────────────────────────────
# 보고서 생성
# ─────────────────────────────────────────────

def generate_reports(db_path: str, reports_dir: str, migration_sources_dir: str) -> None:
    """추출 보고서 + 소스 노트 체크리스트 생성."""
    conn = _get_db(db_path)
    posts = conn.execute(
        "SELECT * FROM posts ORDER BY wp_pub_date ASC"
    ).fetchall()
    conn.close()

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)

    # ── 추출 보고서 ───────────────────────────────────────────────
    total = len(posts)

    # 카테고리 분포
    cat_dist: dict[str, int] = {}
    for p in posts:
        for cat in p["wp_category"].split(","):
            cat = cat.strip()
            cat_dist[cat] = cat_dist.get(cat, 0) + 1
    cat_dist_sorted = sorted(cat_dist.items(), key=lambda x: -x[1])

    # SEO 누락
    seo_missing = []
    for p in posts:
        seo = json.loads(p["wp_seo"] or "{}")
        if not seo.get("focus_keyphrase") and not seo.get("meta_description"):
            seo_missing.append(p["wp_slug"])

    seo_missing_rate = len(seo_missing) / total * 100 if total > 0 else 0

    # 본문 길이 (HTML 기준)
    html_sizes = []
    for p in posts:
        html_path = Path(p["wp_html_path"])
        if html_path.exists():
            # 파일 크기 대신 html_content 길이를 sources JSON에서 추정
            try:
                size = html_path.stat().st_size
            except Exception:
                size = 0
            html_sizes.append(size)

    # 내부 링크 수
    internal_link_counts = []
    all_internal_links: set[str] = set()
    for p in posts:
        sources = json.loads(p["sources"] or "{}")
        links = sources.get("internal_links", [])
        internal_link_counts.append(len(links))
        all_internal_links.update(links)

    # 내부 링크 무결성 검사 (모든 target이 354개 slug 중 하나인가)
    all_slugs = {p["wp_slug"] for p in posts}
    broken_links: list[tuple[str, str]] = []
    for p in posts:
        sources = json.loads(p["sources"] or "{}")
        for link in sources.get("internal_links", []):
            # link는 path 형태 (예: "donoghue-v-stevenson")
            slug_candidate = link.rstrip("/").split("/")[-1]
            if slug_candidate and slug_candidate not in all_slugs:
                broken_links.append((p["wp_slug"], link))

    integrity_pct = (1 - len(broken_links) / max(sum(internal_link_counts), 1)) * 100

    report_md = f"""# WordPress 데이터 추출 보고서
생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 요약

| 항목 | 값 |
|---|---|
| 추출된 글 수 | **{total}개** |
| SEO 메타 완전 누락 글 수 | {len(seo_missing)}개 ({seo_missing_rate:.1f}%) |
| 내부 링크 총 수 (글 전체) | {sum(internal_link_counts)}개 |
| 내부 링크 그래프 무결성 | {integrity_pct:.1f}% |
| 추출 시각 | {datetime.now().isoformat()} |

## 카테고리별 분포

| 카테고리 슬러그 | 글 수 |
|---|---|
"""
    for cat, cnt in cat_dist_sorted:
        report_md += f"| {cat} | {cnt} |\n"

    if html_sizes:
        p50 = int(statistics.median(html_sizes))
        p95 = int(sorted(html_sizes)[int(len(html_sizes) * 0.95)])
        max_size = max(html_sizes)
        report_md += f"""
## 본문 HTML 파일 크기 분포

| 지표 | 값 |
|---|---|
| 중앙값 (p50) | {p50:,} bytes |
| 95th 백분위 (p95) | {p95:,} bytes |
| 최대값 | {max_size:,} bytes |
"""

    report_md += f"""
## 내부 링크 통계

| 지표 | 값 |
|---|---|
| 글당 평균 내부 링크 수 | {sum(internal_link_counts)/max(total,1):.1f}개 |
| 내부 링크 그래프 무결성 | {integrity_pct:.1f}% |
| 미매칭 링크 수 | {len(broken_links)}개 |

"""
    if broken_links[:20]:
        report_md += "### 미매칭 내부 링크 (상위 20개)\n\n"
        report_md += "| 출처 슬러그 | 링크 경로 |\n|---|---|\n"
        for src, link in broken_links[:20]:
            report_md += f"| {src} | {link} |\n"

    if seo_missing[:20]:
        report_md += "\n## SEO 메타 완전 누락 글 (상위 20개)\n\n"
        for s in seo_missing[:20]:
            report_md += f"- {s}\n"

    report_md += f"""
## QA 검증 샘플 (랜덤 5개)

다음 글들은 실제 youngkuklaw.com과 대조 권장:

"""
    sample = random.sample(list(posts), min(5, total))
    for p in sample:
        report_md += f"- [{p['wp_title_ko']}]({p['wp_url']}) → slug: `{p['wp_slug']}`\n"

    (reports_path / "extract_report.md").write_text(report_md, encoding="utf-8")
    print(f"  ✅ extract_report.md 생성 ({total}개 글)")

    # ── 소스 노트 체크리스트 ─────────────────────────────────────
    sources_dir = Path(migration_sources_dir)
    checklist_md = f"""# 소스 노트 준비 체크리스트
생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

> 각 글마다 `migration-sources/<slug>/notes.md` (학습 노트)와 관련 PDF를 준비해주세요.
> AI 파이프라인은 notes.md가 존재하는 글만 자동으로 처리합니다.

| # | 슬러그 | 카테고리 | 발행일 | notes.md | PDF 수 | instructions.md |
|---|---|---|---|---|---|---|
"""
    for i, p in enumerate(posts, 1):
        slug = p["wp_slug"]
        slug_dir = sources_dir / slug
        has_notes = "✅" if (slug_dir / "notes.md").exists() else "❌"
        pdf_count = len(list(slug_dir.glob("*.pdf"))) if slug_dir.exists() else 0
        has_instructions = "✅" if (slug_dir / "instructions.md").exists() else "—"
        pub_date = p["wp_pub_date"][:10] if p["wp_pub_date"] else "—"
        checklist_md += f"| {i} | `{slug}` | {p['wp_category']} | {pub_date} | {has_notes} | {pdf_count} | {has_instructions} |\n"

    ready_count = sum(
        1 for p in posts
        if (sources_dir / p["wp_slug"] / "notes.md").exists()
    )
    checklist_md += f"\n**준비 완료:** {ready_count}/{total}개\n"

    (reports_path / "source_notes_checklist.md").write_text(checklist_md, encoding="utf-8")
    print(f"  ✅ source_notes_checklist.md 생성 (준비 완료: {ready_count}/{total})")


# ─────────────────────────────────────────────
# 메인 추출 함수
# ─────────────────────────────────────────────

def extract_all(
    xml_path: str,
    db_path: str,
    output_dir: str,
    reports_dir: str,
    migration_sources_dir: str,
) -> int:
    """
    전체 추출 실행.
    Returns: 새로 삽입된 글 수
    """
    xml_path = Path(xml_path)
    if not xml_path.exists():
        raise FileNotFoundError(f"WP XML 파일을 찾을 수 없습니다: {xml_path}")

    print(f"📂 XML 파싱 중: {xml_path} ({xml_path.stat().st_size:,} bytes)")

    # lxml 파싱 (큰 파일 대응 — iterparse 대신 전체 파싱 후 xpath)
    with open(xml_path, "rb") as f:
        tree = etree.parse(f)

    root = tree.getroot()
    items = root.xpath("//item")
    print(f"  ℹ️  총 <item> 수: {len(items)}")

    conn = _get_db(db_path)

    inserted = 0
    skipped = 0
    failed = 0

    for i, item in enumerate(items, 1):
        try:
            post = parse_post(item)
            if post is None:
                continue  # post/publish 아닌 항목 skip

            # HTML 캐시 저장
            html_path = _save_html_cache(post, output_dir)

            # DB 삽입
            ok = _insert_post(conn, post, html_path)
            if ok:
                inserted += 1
                if inserted % 50 == 0:
                    print(f"  → {inserted}개 삽입 완료...")
                    conn.commit()
            else:
                skipped += 1

        except Exception as e:
            failed += 1
            slug = item.xpath("wp:post_name/text()", namespaces=NS)
            slug_str = slug[0] if slug else f"item#{i}"
            print(f"  ⚠️  파싱 실패: {slug_str} — {e}")

    conn.commit()
    conn.close()

    print(f"\n✅ 추출 완료: 삽입 {inserted}개 | 스킵(중복) {skipped}개 | 실패 {failed}개")

    # 보고서 생성
    print("\n📊 보고서 생성 중...")
    generate_reports(db_path, reports_dir, migration_sources_dir)

    return inserted


def sources_status(db_path: str, migration_sources_dir: str) -> None:
    """migration-sources/ 준비 현황을 터미널에 출력."""
    conn = _get_db(db_path)
    posts = conn.execute(
        "SELECT wp_slug, wp_category, wp_pub_date, status FROM posts ORDER BY wp_pub_date ASC"
    ).fetchall()
    conn.close()

    sources_dir = Path(migration_sources_dir)
    total = len(posts)
    ready = 0

    print(f"\n{'슬러그':<50} {'카테고리':<20} {'notes':>6} {'PDF':>4} {'상태':>15}")
    print("-" * 100)
    for p in posts:
        slug = p["wp_slug"]
        slug_dir = sources_dir / slug
        has_notes = "✅" if (slug_dir / "notes.md").exists() else "❌"
        pdf_count = len(list(slug_dir.glob("*.pdf"))) if slug_dir.exists() else 0
        if has_notes == "✅":
            ready += 1
        print(f"{slug:<50} {p['wp_category'][:19]:<20} {has_notes:>6} {pdf_count:>4} {p['status']:>15}")

    print("-" * 100)
    print(f"총 {total}개 | 노트 준비 완료: {ready}개 ({ready/max(total,1)*100:.1f}%)")
