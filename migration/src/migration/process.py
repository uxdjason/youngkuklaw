"""
process.py — 글 1건 처리 파이프라인 (Phase 4)

소스 우선순위:
  1. migration-sources/<slug>/confirmed_pdfs.yaml (사용자 확인 완료)
  2. confirmed_pdfs.yaml 없으면 처리 불가 → resolve-sources 실행 필요 메시지

흐름:
  [resolve-sources] 단계 (선행 필수):
    score_pdf_candidates() → 사용자 확인 → confirmed_pdfs.yaml 저장

  [process / run] 단계:
    confirmed_pdfs.yaml 로드 → research → write_en → write_ko → seo → awaiting_review

재시도 정책 (revision_scope):
  - full: research부터 다시
  - write_only: research_json 캐시 재사용, write_en/write_ko/seo 재실행
  - seo_only: en/ko 그대로, seo만 재실행
"""

import asyncio
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

def cprint(msg: str, out: Path = None):
    print(msg)
    if out:
        try:
            with open(out / "progress.log", "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass

import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

from migration.ai.llm import LLMClient

# ─────────────────────────────────────────────
# 경로 설정
# ─────────────────────────────────────────────

PROJECT_ROOT    = Path(__file__).resolve().parents[3]
DB_PATH         = str(PROJECT_ROOT / "migration/state.db")
OUTPUT_DIR      = str(PROJECT_ROOT / "output-storage")
SOURCES_DIR     = str(PROJECT_ROOT / "migration-sources")
LAW_SOURCES_DIR = str(PROJECT_ROOT / "law-sources")
PROMPTS_DIR     = Path(__file__).parent / "ai/prompts"
GLOSSARY_PATH   = Path(__file__).parent / "ai/glossary.yaml"

CONFIRMED_PDFS_FILENAME = "confirmed_pdfs.yaml"

# ─────────────────────────────────────────────
# 카테고리 → law-sources 폴더 매핑
# ─────────────────────────────────────────────

CATEGORY_TO_LAW_FOLDER: dict[str, list[str]] = {
    "contract-law-cases":  ["contract case"],
    "tort-law-cases":      ["tort case"],
    "public-law-cases":    ["public case"],
    "criminal-law-cases":  ["criminal case"],
    "land-law-cases":      ["land case"],
    "equity-law-cases":    ["equity case"],
    "case-law":            ["contract case", "tort case", "public case",
                            "criminal case", "land case", "equity case", "general case"],
    "contract-law":        ["contract"],
    "tort-law":            ["tort"],
    "public-law":          ["public"],
    "criminal-law":        ["criminal"],
    "land-law":            ["land"],
    "equity-law":          ["equity"],
    "english-law":         ["general"],
}

# case-law 카테고리 여부 판단용
CASE_LAW_CATEGORIES = {
    "contract-law-cases", "tort-law-cases", "public-law-cases",
    "criminal-law-cases", "land-law-cases", "equity-law-cases",
    "case-law", "general-case",
}


# ─────────────────────────────────────────────
# DB 유틸리티
# ─────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _update_status(post_id: int, status: str, error: Optional[str] = None) -> None:
    conn = _db()
    if error:
        conn.execute(
            "UPDATE posts SET status=?, last_error=?, attempts=attempts+1, updated_at=datetime('now') WHERE id=?",
            (status, error[:2000], post_id),
        )
    else:
        conn.execute(
            "UPDATE posts SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, post_id),
        )
    conn.commit()
    conn.close()


def _set_research_path(post_id: int, path: str) -> None:
    conn = _db()
    conn.execute("UPDATE posts SET research_json_path=?, updated_at=datetime('now') WHERE id=?", (path, post_id))
    conn.commit()
    conn.close()


def _set_output_dir(post_id: int, path: str) -> None:
    conn = _db()
    conn.execute("UPDATE posts SET output_dir=?, updated_at=datetime('now') WHERE id=?", (path, post_id))
    conn.commit()
    conn.close()


def get_post(post_id: int) -> Optional[sqlite3.Row]:
    conn = _db()
    row = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    conn.close()
    return row


# ─────────────────────────────────────────────
# 텍스트 추출 유틸리티
# ─────────────────────────────────────────────

def html_to_plaintext(html: str) -> str:
    """HTML → 평문 (참조용 컨텍스트 빌드). 링크는 [텍스트](URL) 형태로 보존."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for comment in soup.find_all(string=lambda t: t and t.strip().startswith("wp:")):
        try:
            comment.extract()
        except Exception:
            pass
    # <a> 태그를 마크다운 링크로 변환
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text()
        if href and text:
            a.replace_with(f"[{text}]({href})")
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:8000]


def extract_wp_case_metadata(html: str) -> dict:
    """WP HTML에서 판례 메타데이터(Citation, Court, Claimant, Defendant, CourtLink)를 직접 파싱."""
    if not html:
        return {}
    soup = BeautifulSoup(html, "lxml")
    result = {}
    headings = soup.find_all(["h2", "h3"])
    field_map = {
        "citation:": "citation",
        "court:": "court",
        "claimant:": "claimant",
        "defendant:": "defendant",
        "judges:": "judges",
    }
    for h in headings:
        key = h.get_text(strip=True).lower()
        if key in field_map:
            field = field_map[key]
            sibling = h.find_next_sibling(["p", "div"])
            if sibling:
                # courtLink: Citation 필드의 <a> href
                if field == "citation":
                    a_tag = sibling.find("a", href=True)
                    if a_tag:
                        result["courtLink"] = a_tag.get("href", "")
                    result["citation"] = sibling.get_text(strip=True)
                else:
                    result[field] = sibling.get_text(strip=True)
    return result


def extract_pdf_texts(pdf_paths: list[str], max_chars_per_pdf: int = 10000) -> list[str]:
    """PDF 파일들을 텍스트로 변환."""
    texts = []
    try:
        import pymupdf
        for pdf_path in pdf_paths:
            p = Path(pdf_path)
            if not p.exists():
                print(f"  ⚠️  PDF 없음: {p}")
                continue
            try:
                doc = pymupdf.open(str(p))
                text = ""
                for page in doc:
                    text += page.get_text()
                doc.close()
                texts.append(f"[PDF: {p.name}]\n{text[:max_chars_per_pdf]}")
            except Exception as e:
                texts.append(f"[PDF: {p.name}] 추출 실패: {e}")
    except ImportError:
        print("  ⚠️  PyMuPDF 미설치. PDF 추출 건너뜀.")
    return texts


# ─────────────────────────────────────────────
# PDF 후보 탐색 (점수 기반, 자동 사용 안 함)
# ─────────────────────────────────────────────

def score_pdf_candidates(
    title: str,
    slug: str,
    categories: str,
) -> list[dict]:
    """
    law-sources/ 폴더에서 PDF 후보를 찾아 신뢰도 점수와 함께 반환.
    자동으로 사용하지 않음 — resolve-sources 확인 단계에서만 호출.

    Returns: [
        {
            'path': str,
            'filename': str,
            'folder': str,
            'score': float,       # 0~100
            'matched_terms': list[str],
        }, ...
    ] sorted by score DESC
    """
    law_sources = Path(LAW_SOURCES_DIR)
    if not law_sources.exists():
        return []

    noise = {"case", "law", "the", "a", "an", "of", "in", "and", "v",
             "cases", "re", "ex", "parte", "vs", "ltd", "plc"}

    # is_case_law 판단
    cat_list = [c.strip() for c in categories.split(",")]
    is_case_law = any(c in CASE_LAW_CATEGORIES for c in cat_list)

    # 키워드 추출 (slug + title 복합)
    slug_words = set(slug.lower().replace("-", " ").split()) - noise
    title_clean = re.sub(r"[\[\](){}]", " ", title.lower())
    title_words = set(title_clean.split()) - noise
    years = set(re.findall(r"\b(1[0-9]{3}|20[0-9]{2})\b", title))
    keywords = (slug_words | title_words) - noise

    # 카테고리 기반 탐색 폴더
    folders_to_search: list[Path] = []
    for cat in cat_list:
        for folder_name in CATEGORY_TO_LAW_FOLDER.get(cat, []):
            folder = law_sources / folder_name
            if folder.exists() and folder not in folders_to_search:
                folders_to_search.append(folder)
    if not folders_to_search:
        folders_to_search = [d for d in law_sources.iterdir() if d.is_dir()]

    candidates: list[dict] = []
    for folder in folders_to_search:
        for pdf in sorted([p for p in folder.iterdir() if p.suffix.lower() == ".pdf"]):
            stem_lower = re.sub(r"[\[\](){}]", " ", pdf.stem.lower())
            stem_words = set(stem_lower.split()) - noise

            # 키워드 일치 점수 (최대 60점)
            matched_kw = keywords & stem_words
            kw_score = (len(matched_kw) / max(len(keywords), 1)) * 60

            # 연도 일치 보너스 (20점)
            matched_years = years & set(re.findall(r"\b\d{4}\b", stem_lower))
            year_score = 20.0 if matched_years else 0.0

            # 폴더 유형 보너스 (10점)
            folder_bonus = 0.0
            if is_case_law and "case" in folder.name.lower():
                folder_bonus = 10.0
            elif not is_case_law and "case" not in folder.name.lower():
                folder_bonus = 10.0

            # 당사자 이름 일치 보너스 판례용 (최대 10점)
            party_bonus = 0.0
            if is_case_law:
                parties = [w for w in slug.replace("-", " ").split()
                           if len(w) > 3 and w.lower() not in noise]
                party_matches = sum(1 for p in parties if p.lower() in stem_lower)
                party_bonus = min(party_matches * 5.0, 10.0)

            score = kw_score + year_score + folder_bonus + party_bonus

            if score > 0:
                candidates.append({
                    "path": str(pdf.resolve()),
                    "filename": pdf.name,
                    "folder": folder.name,
                    "score": round(score, 1),
                    "matched_terms": sorted(matched_kw | matched_years),
                })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


# ─────────────────────────────────────────────
# confirmed_pdfs.yaml 관리
# ─────────────────────────────────────────────

def load_confirmed_sources(slug: str) -> Optional[dict]:
    """
    migration-sources/<slug>/confirmed_pdfs.yaml 로드.
    없으면 None 반환 (→ resolve-sources 실행 필요).
    """
    path = Path(SOURCES_DIR) / slug / CONFIRMED_PDFS_FILENAME
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if data and data.get("confirmed") else None


def save_confirmed_sources(
    slug: str,
    pdf_paths: list[str],
    use_web_supplement: bool,
) -> None:
    """사용자가 확인한 PDF 리스트를 confirmed_pdfs.yaml에 저장."""
    dest_dir = Path(SOURCES_DIR) / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "confirmed": True,
        "pdf_paths": pdf_paths,
        "use_web_search_supplement": use_web_supplement,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(dest_dir / CONFIRMED_PDFS_FILENAME, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


# ─────────────────────────────────────────────
# 기타 유틸리티
# ─────────────────────────────────────────────

def load_glossary() -> str:
    """glossary.yaml → AI 프롬프트 삽입용 텍스트."""
    if not GLOSSARY_PATH.exists():
        return ""
    with open(GLOSSARY_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    lines = []
    if "style_rules" in data:
        lines.append("### Style Rules")
        for rule in data["style_rules"]:
            lines.append(f"- {rule}")
        lines.append("")
    if "terms" in data:
        lines.append("### Key Legal Terms (EN → KO)")
        for term in data["terms"]:
            ko = term.get("ko", "")
            note = term.get("note", "")
            line = f"- **{term['en']}** → {ko}"
            if note:
                line += f" ({note})"
            lines.append(line)
    return "\n".join(lines)


def load_prompt(name: str) -> str:
    """프롬프트 파일 로드."""
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"프롬프트 파일 없음: {path}")
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────
# 산출물 저장 유틸리티
# ─────────────────────────────────────────────

def _output_dir(slug: str) -> Path:
    return Path(OUTPUT_DIR) / "migration" / slug


def _ensure_output_dirs(slug: str) -> Path:
    out = _output_dir(slug)
    (out / "reference" / "source_notes").mkdir(parents=True, exist_ok=True)
    return out


def _snapshot_sources(slug: str, sources_path: Path) -> None:
    """migration-sources/<slug>/ → output-storage/.../reference/source_notes/ 스냅샷."""
    if not sources_path.exists():
        return
    dest = _output_dir(slug) / "reference" / "source_notes"
    for f in sources_path.iterdir():
        if f.is_file():
            shutil.copy2(f, dest / f.name)


def _save_web_research_md(slug: str, research_json: dict) -> None:
    """research_json → web_research.md."""
    out = _output_dir(slug) / "reference" / "web_research.md"
    lines = [
        f"# Web Research: {slug}",
        f"생성일시: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## 주제 요약",
        research_json.get("topic_summary", ""),
        "",
        "## 소스 기반 핵심 사실",
        "",
    ]
    for fact in research_json.get("key_facts_from_sources", []):
        lines.append(f"- **[{fact.get('source', '?')}]** {fact.get('claim', '')} — `{fact.get('citation', '')}`")
    lines += ["", "## 웹 검색 결과", ""]
    for wf in research_json.get("web_findings", []):
        lines.append(f"### [{wf.get('title', wf.get('url', ''))}]({wf.get('url', '')})")
        lines.append(f"*{wf.get('fetched_at', '')}*")
        lines.append("")
        lines.append(wf.get("summary", ""))
        lines.append("")
    if research_json.get("open_questions"):
        lines += ["## 미결 사항 (검수 시 확인 필요)", ""]
        for q in research_json["open_questions"]:
            lines.append(f"- {q}")
    out.write_text("\n".join(lines), encoding="utf-8")


def _extract_json_from_response(text: str) -> dict:
    """LLM 응답에서 JSON 파싱."""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end+1]
    return json.loads(text)


# ─────────────────────────────────────────────
# 파이프라인 단계별 함수
# ─────────────────────────────────────────────

async def _step_research(
    llm: LLMClient,
    post: sqlite3.Row,
    slug: str,
    out: Path,
    web_urls: list[str],
    user_instructions: str,
    pdf_texts: list[str],
    wp_plaintext: str,
    revision_scope: Optional[str],
    use_web_search: bool,
) -> dict:
    """
    Research 단계.
    use_web_search=True : PDF 없음, web search 주 소스
    use_web_search=False: PDF 있음, web search는 최신 업데이트 보완용
    """
    # 캐시 확인
    if revision_scope in ("write_only", "seo_only") and post["research_json_path"]:
        cache_path = Path(post["research_json_path"])
        if cache_path.exists():
            print(f"  ♻️  research 캐시 재사용: {cache_path.name}")
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)

    _update_status(post["id"], "researching")
    source_mode = "web search (폴백)" if use_web_search else f"PDF {len(pdf_texts)}개 (web search 없음)"
    cprint(f"  🔍 Research 시작 [{source_mode}]...", out)

    system = load_prompt("research")
    pdf_combined = "\n\n".join(pdf_texts) if pdf_texts else "(PDF 없음 — web search 사용)"

    prompt = system.replace("{topic}", post["wp_title_ko"]) \
                   .replace("{category}", post["wp_category"]) \
                   .replace("{wp_original_plaintext}", wp_plaintext[:4000]) \
                   .replace("{web_urls}", "\n".join(web_urls) if web_urls else "None provided") \
                   .replace("{pdf_texts}", pdf_combined[:12000])

    if user_instructions:
        prompt += f"\n\n## User Instructions\n{user_instructions}"

    if use_web_search:
        # PDF 없음 → agentic web search 루프
        result = await llm.acall_research(
            prompt,
            system="",
            post_id=post["id"],
            cache_system=False,
        )
    else:
        # PDF 있음 → 단순 1회 호출 (web search 없이 훨씬 빠름)
        result = await llm.acall(
            prompt,
            system="",
            post_id=post["id"],
            phase="research",
            max_tokens=8192,
            cache_system=False,
        )

    research_json = _extract_json_from_response(result.text)

    research_cache_path = out / "reference" / "research_cache.json"
    research_cache_path.write_text(json.dumps(research_json, ensure_ascii=False, indent=2), encoding="utf-8")
    _set_research_path(post["id"], str(research_cache_path))

    _save_web_research_md(slug, research_json)
    cprint(f"  ✅ Research 완료 (웹검색 {result.usage.tool_calls}회, ${result.cost_usd:.4f})", out)
    return research_json


async def _step_write_en(
    llm: LLMClient,
    post: sqlite3.Row,
    out: Path,
    research_json: dict,
    glossary_text: str,
    available_cases_text: str,
    revision_scope: Optional[str],
) -> str:
    if revision_scope == "seo_only":
        en_path = out / "en.md"
        if en_path.exists():
            print(f"  ♻️  en.md 캐시 재사용")
            return en_path.read_text(encoding="utf-8")

    _update_status(post["id"], "writing_en")
    cprint(f"  ✍️  영문 작성 중...", out)

    system = load_prompt("write_en")
    prompt = system.replace("{glossary}", glossary_text) \
                   .replace("{available_cases}", available_cases_text) \
                   .replace("{wp_slug}", post["wp_slug"]) \
                   .replace("{category}", post["wp_category"]) \
                   .replace("{research_json}", json.dumps(research_json, ensure_ascii=False))

    result = await llm.acall(
        prompt, system="", post_id=post["id"], phase="write_en", max_tokens=8192, cache_system=False,
    )

    en_md = result.text.strip()
    en_md = _remove_self_links(en_md, post["wp_slug"])
    (out / "en.md").write_text(en_md, encoding="utf-8")
    cprint(f"  ✅ 영문 작성 완료 ({len(en_md)}자, ${result.cost_usd:.4f})", out)
    return en_md


async def _step_write_ko(
    llm: LLMClient,
    post: sqlite3.Row,
    out: Path,
    research_json: dict,
    en_md: str,
    glossary_text: str,
    available_cases_text: str,
    revision_scope: Optional[str],
) -> str:
    if revision_scope == "seo_only":
        ko_path = out / "ko.md"
        if ko_path.exists():
            print(f"  ♻️  ko.md 캐시 재사용")
            return ko_path.read_text(encoding="utf-8")

    _update_status(post["id"], "writing_ko")
    cprint(f"  ✍️  한국어 작성 중...", out)

    system = load_prompt("write_ko")
    prompt = system.replace("{glossary}", glossary_text) \
                   .replace("{available_cases}", available_cases_text) \
                   .replace("{wp_slug}", post["wp_slug"]) \
                   .replace("{category}", post["wp_category"]) \
                   .replace("{research_json}", json.dumps(research_json, ensure_ascii=False)) \
                   .replace("{en_md}", en_md)

    result = await llm.acall(
        prompt, system="", post_id=post["id"], phase="write_ko", max_tokens=8192, cache_system=False,
    )

    ko_md = result.text.strip()
    ko_md = _remove_self_links(ko_md, post["wp_slug"])
    (out / "ko.md").write_text(ko_md, encoding="utf-8")
    cprint(f"  ✅ 한국어 작성 완료 ({len(ko_md)}자, ${result.cost_usd:.4f})", out)
    return ko_md


async def _step_wp_priority_en(
    llm: LLMClient,
    post: sqlite3.Row,
    out: Path,
    ko_md: str,
    glossary_text: str,
    available_cases_text: str,
    revision_scope: Optional[str],
) -> str:
    if revision_scope == "seo_only":
        en_path = out / "en.md"
        if en_path.exists():
            return en_path.read_text(encoding="utf-8")

    _update_status(post["id"], "writing_en")
    cprint(f"  ✍️  영문 번역 중 (기존 WP 우선 모드 — KO 번역)...", out)

    system = load_prompt("wp_priority_en")
    prompt = system.replace("{available_cases}", available_cases_text) \
                   .replace("{wp_slug}", post["wp_slug"]) \
                   .replace("{category}", post["wp_category"]) \
                   .replace("{ko_md}", ko_md)

    result = await llm.acall(
        prompt, system="", post_id=post["id"], phase="write_en", max_tokens=8192, cache_system=False,
    )

    en_md = result.text.strip()
    en_md = _remove_self_links(en_md, post["wp_slug"])
    (out / "en.md").write_text(en_md, encoding="utf-8")
    cprint(f"  ✅ 영문 번역 완료 ({len(en_md)}자, ${result.cost_usd:.4f})", out)
    return en_md


async def _step_wp_priority_ko(
    llm: LLMClient,
    post: sqlite3.Row,
    out: Path,
    wp_plaintext: str,
    glossary_text: str,
    available_cases_text: str,
    revision_scope: Optional[str],
) -> str:
    if revision_scope == "seo_only":
        ko_path = out / "ko.md"
        if ko_path.exists():
            return ko_path.read_text(encoding="utf-8")

    _update_status(post["id"], "writing_ko")
    cprint(f"  ✍️  한국어 작성 중 (기존 WP 우선 모드)...", out)

    system = load_prompt("wp_priority_ko")
    prompt = system.replace("{glossary}", glossary_text) \
                   .replace("{available_cases}", available_cases_text) \
                   .replace("{wp_slug}", post["wp_slug"]) \
                   .replace("{category}", post["wp_category"]) \
                   .replace("{wp_original_plaintext}", wp_plaintext)

    result = await llm.acall(
        prompt, system="", post_id=post["id"], phase="write_ko", max_tokens=8192, cache_system=False,
    )

    ko_md = result.text.strip()
    ko_md = _remove_self_links(ko_md, post["wp_slug"])
    (out / "ko.md").write_text(ko_md, encoding="utf-8")
    cprint(f"  ✅ 한국어 작성 완료 ({len(ko_md)}자, ${result.cost_usd:.4f})", out)
    return ko_md


def _remove_self_links(text: str, slug: str) -> str:
    """자기 자신에 대한 마크다운 링크를 제거하고 링크 텍스트만 남긴다."""
    # [Link Text](/slug) 또는 [Link Text](/ko/slug) 패턴 제거 (nested brackets 지원)
    pattern = re.compile(
        r'\[(.*?)\]\(\/?(?:ko\/)?%s\/?\)' % re.escape(slug)
    )
    return pattern.sub(r'\1', text)


async def _step_seo(
    llm: LLMClient,
    post: sqlite3.Row,
    out: Path,
    en_md: str,
    ko_md: str,
) -> dict:
    _update_status(post["id"], "seo")
    cprint(f"  🔖 SEO 메타 생성 중...", out)

    wp_seo = json.loads(post["wp_seo"] or "{}")
    system = load_prompt("seo")
    prompt = system.replace("{category}", post["wp_category"]) \
                   .replace("{wp_slug}", post["wp_slug"]) \
                   .replace("{wp_seo_legacy}", json.dumps(wp_seo, ensure_ascii=False)) \
                   .replace("{en_md_final}", en_md) \
                   .replace("{ko_md_final}", ko_md)

    result = await llm.acall(
        prompt, system="", post_id=post["id"], phase="seo", max_tokens=1024, cache_system=False,
    )

    seo_json = _extract_json_from_response(result.text)
    for lang in ("en", "ko"):
        if lang in seo_json:
            seo_json[lang]["slug"] = post["wp_slug"]

    cprint(f"  ✅ SEO 메타 생성 완료 (${result.cost_usd:.4f})", out)
    return seo_json


def _save_meta_yaml(slug: str, post: sqlite3.Row, seo_json: dict, sources_info: dict, out: Path) -> None:
    meta = {
        "slug": slug,
        "wp_id": post["id"],
        "category": post["wp_category"],
        "pub_date": post["wp_pub_date"],
        "modified_date": post["wp_modified_date"],
        "status": "awaiting_review",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "en": seo_json.get("en", {}),
        "ko": seo_json.get("ko", {}),
        "shared": seo_json.get("shared", {}),
        "sources": {
            "notes_path": sources_info.get("notes_path"),
            "pdf_paths": sources_info.get("pdf_paths", []),
            "wp_original_html": str(out / "reference" / "wp_original.html"),
        },
    }
    with open(out / "meta.yaml", "w", encoding="utf-8") as f:
        yaml.dump(meta, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _build_frontmatter(slug: str, post: sqlite3.Row, seo_json: dict, lang: str) -> str:
    seo = seo_json.get(lang, {})
    shared = seo_json.get("shared", {})
    fm = {
        "title": seo.get("seo_title", post["wp_title_ko"]),
        "slug": slug,
        "lang": lang,
        "category": post["wp_category"],
        "pubDate": post["wp_pub_date"],
        "updatedDate": post["wp_modified_date"] or post["wp_pub_date"],
        "description": seo.get("meta_description", ""),
        "seoTitle": seo.get("seo_title", ""),
        "metaDescription": seo.get("meta_description", ""),
        "focusKeyphrase": seo.get("focus_keyphrase", ""),
        "longTailKeywords": seo.get("long_tail_keywords", []),
        "wp_legacy_id": post["id"],
        "reviewed_by": "pending",
        "reviewed_at": None,
        "is_dummy": False,
    }
    # Case law metadata — inject only if present
    is_case = "case" in post["wp_category"]
    if is_case:
        if shared.get("citation"):
            fm["citation"] = shared["citation"]
        if shared.get("court"):
            fm["court"] = shared["court"]
        if shared.get("claimant"):
            fm["claimant"] = shared["claimant"]
        if shared.get("defendant"):
            fm["defendant"] = shared["defendant"]
        if shared.get("courtLink"):
            fm["courtLink"] = shared["courtLink"]

    yaml_str = yaml.dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{yaml_str}---\n\n"



def get_available_cases_db() -> str:
    """DB에서 판례 목록을 불러와 프롬프트에 주입할 텍스트 생성"""
    conn = _db()
    rows = conn.execute("SELECT wp_title_ko, wp_slug FROM posts WHERE wp_category LIKE '%case%'").fetchall()
    conn.close()
    
    if not rows:
        return "None"
        
    cases = []
    for r in rows:
        title = r["wp_title_ko"]
        m = re.match(r"^(.*? (?:\[\d{4}\]|\(\d{4}\)))", title)
        short_title = m.group(1) if m else title
        cases.append(f"- {short_title}: /{r['wp_slug']}")
    return "\n".join(cases)


# ─────────────────────────────────────────────
# 메인 process_post 함수
# ─────────────────────────────────────────────

async def process_post(
    post_id: int,
    pdf_paths: list[str],
    web_urls: list[str],
    user_instructions: str = "",
    revision_scope: Optional[str] = None,
    mode: str = "대폭 개선 옵션",
    verbose: bool = True,
) -> str:
    """
    글 1건 처리 파이프라인.
    UI에서 전달받은 pdf_paths, web_urls를 바탕으로 실행.
    """
    post = get_post(post_id)
    if post is None:
        raise ValueError(f"post_id={post_id}를 DB에서 찾을 수 없습니다.")

    slug = post["wp_slug"]
    # 출력 폴더
    out = _ensure_output_dirs(slug)
    _set_output_dir(post_id, str(out))
    
    # 이전 로그 초기화
    if (out / "progress.log").exists():
        (out / "progress.log").unlink()

    if verbose:
        print(f"\n{'='*60}")
        print(f"🚀 처리 시작: [{post_id}] {slug}")
        print(f"   카테고리: {post['wp_category']}")
        print(f"   제목: {post['wp_title_ko']}")
        print(f"   PDF 개수: {len(pdf_paths)}")
        print(f"   URL 개수: {len(web_urls)}")
        print(f"{'='*60}")

    _update_status(post_id, "researching")

    use_web_search_mode = len(pdf_paths) == 0

    pdf_texts = extract_pdf_texts(pdf_paths)
    cprint(f"  📄 PDF: {len(pdf_paths)}개 로드 | web search: {'주 소스' if use_web_search_mode else '보완용'}", out)

    # WP 원문 HTML → 평문
    wp_html_path = Path(post["wp_html_path"]) if post["wp_html_path"] else None
    wp_plaintext = ""
    if wp_html_path and wp_html_path.exists():
        wp_plaintext = html_to_plaintext(wp_html_path.read_text(encoding="utf-8"))

    log_path = str(out / "ai_log.jsonl")
    llm = LLMClient(db_path=DB_PATH, log_path=log_path)

    try:
        glossary_text = load_glossary()
        available_cases_text = get_available_cases_db()
        sources_info = {
            "pdf_paths": pdf_paths,
            "web_urls": web_urls,
            "user_instructions": user_instructions
        }

        if mode == "기존 WP 우선 모드":
            # 리서치 건너뛰기: KO 먼저 작성, EN은 KO를 번역
            research_json = {}
            ko_md = await _step_wp_priority_ko(llm, post, out, wp_plaintext, glossary_text, available_cases_text, revision_scope)
            en_md = await _step_wp_priority_en(llm, post, out, ko_md, glossary_text, available_cases_text, revision_scope)
        else:
            # Step 1: Research
            research_json = await _step_research(
                llm, post, slug, out, web_urls, user_instructions, pdf_texts, wp_plaintext,
                revision_scope, use_web_search=use_web_search_mode,
            )
            post = get_post(post_id)

            # Step 2: write_en
            en_md = await _step_write_en(llm, post, out, research_json, glossary_text, available_cases_text, revision_scope)

            # Step 3: write_ko
            ko_md = await _step_write_ko(llm, post, out, research_json, en_md, glossary_text, available_cases_text, revision_scope)

        # Step 4: SEO
        seo_json = await _step_seo(llm, post, out, en_md, ko_md)

        # WP HTML에서 판례 메타데이터 직접 파싱 (AI 추출보다 신뢰도 높음)
        is_case = "case" in post["wp_category"]
        if is_case and wp_html_path and wp_html_path.exists():
            wp_meta = extract_wp_case_metadata(wp_html_path.read_text(encoding="utf-8"))
            shared = seo_json.setdefault("shared", {})
            # WP에서 파싱한 값으로 덮어쓰기 (비어있으면 AI 추출값 유지)
            for field in ("citation", "court", "claimant", "defendant", "courtLink"):
                if wp_meta.get(field):
                    shared[field] = wp_meta[field]

        # 산출물 저장
        (out / "en.md").write_text(_build_frontmatter(slug, post, seo_json, "en") + en_md, encoding="utf-8")
        (out / "ko.md").write_text(_build_frontmatter(slug, post, seo_json, "ko") + ko_md, encoding="utf-8")
        _save_meta_yaml(slug, post, seo_json, sources_info, out)

        _update_status(post_id, "awaiting_review")
        print(f"\n✅ [{slug}] 처리 완료 → awaiting_review")
        print(f"   출력: {out}")
        return "awaiting_review"

    except Exception as e:
        import traceback
        err_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}"
        _update_status(post_id, "failed", err_msg)
        print(f"\n❌ [{slug}] 처리 실패: {e}")
        raise


# ─────────────────────────────────────────────
# 큐 러너
# ─────────────────────────────────────────────

async def run_queue(workers: int = 4, limit: Optional[int] = None) -> None:
    """
    confirmed_pdfs.yaml + notes.md 모두 준비된 글을 발행일 오래된 순으로 처리.
    """
    import os
    max_review_queue = int(os.getenv("MAX_CONCURRENT_REVIEW_QUEUE", "20"))

    conn = _db()
    rows = conn.execute(
        "SELECT id, wp_slug FROM posts WHERE status='pending' ORDER BY wp_pub_date ASC"
    ).fetchall()
    conn.close()

    if not rows:
        print("📭 처리할 글이 없습니다 (status=pending인 글 0개).")
        return

    ready = []
    skip_no_notes = 0
    skip_no_confirmed = 0
    for row in rows:
        notes = Path(SOURCES_DIR) / row["wp_slug"] / "notes.md"
        if not notes.exists():
            skip_no_notes += 1
            continue
        confirmed = load_confirmed_sources(row["wp_slug"])
        if confirmed is None:
            skip_no_confirmed += 1
            continue
        ready.append(row["id"])

    if limit:
        ready = ready[:limit]

    print(f"📋 큐 시작: {len(ready)}개 처리 예정")
    print(f"   건너뜀: 소스 노트 없음 {skip_no_notes}개 | PDF 확인 미완료 {skip_no_confirmed}개")
    if skip_no_confirmed > 0:
        print(f"   → PDF 확인 필요: python run_migration.py resolve-sources")

    sem = asyncio.Semaphore(workers)

    async def process_one(post_id: int) -> None:
        async with sem:
            while True:
                conn = _db()
                review_count = conn.execute(
                    "SELECT COUNT(*) FROM posts WHERE status='awaiting_review'"
                ).fetchone()[0]
                conn.close()
                if review_count < max_review_queue:
                    break
                print(f"  ⏳ awaiting_review 적체({review_count}개) → 60초 대기...")
                await asyncio.sleep(60)

            try:
                await process_post(post_id, verbose=True)
            except Exception as e:
                print(f"  ❌ post_id={post_id} 실패: {e}")

    tasks = [asyncio.create_task(process_one(pid)) for pid in ready]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        print("\n⚠️  Ctrl+C 감지 — 현재 진행 중인 글은 완료 후 종료합니다.")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    conn = _db()
    summary = conn.execute(
        "SELECT status, COUNT(*) FROM posts GROUP BY status ORDER BY COUNT(*) DESC"
    ).fetchall()
    conn.close()
    print("\n📊 최종 상태:")
    for row in summary:
        print(f"  {row[0]:<25} {row[1]:>5}개")
