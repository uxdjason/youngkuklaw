import json
import sqlite3
import yaml
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path("migration/state.db")
OUTPUT_BASE = Path("output-storage/migration")
ASTRO_POSTS_EN = Path("src/content/posts/en")
ASTRO_POSTS_KO = Path("src/content/posts/ko")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def synthesize_frontmatter(post_row, meta_data, lang: str):
    """
    YAML Frontmatter 합성
    """
    slug = post_row["wp_slug"]
    
    # DB의 pub_date 가져오기
    pub_date = post_row["wp_pub_date"]
    if not pub_date:
        pub_date = datetime.now(timezone.utc).isoformat()
    elif not pub_date.endswith("Z") and "+" not in pub_date:
        pub_date += "Z" # 시간대 정보 추가
        
    category_val = post_row["wp_category"] if post_row["wp_category"] else "uncategorized"
    if "," in category_val:
        category_val = category_val.split(",")[0].strip()

    seo = meta_data.get(lang, {})
    shared = meta_data.get("shared", {})
    
    # 판례의 경우 title을 순수 사건 이름으로 정리 ([, ( 앞부분까지)
    title_raw = post_row["wp_title_ko"]
    clean_title = title_raw
    if "case" in category_val:
        import re
        # '[' 또는 '(' 기준으로 스플릿하여 앞부분만 추출
        match = re.split(r'\[|\(', title_raw)
        if match:
            clean_title = match[0].strip()
            
    # SEO title이 없을 경우 대비
    if not seo.get("seo_title"):
        seo_title = clean_title
    else:
        seo_title = seo["seo_title"]
    
    citation_raw = shared.get("citation")
    if citation_raw and ("[" in citation_raw or "(" in citation_raw):
        import re
        match = re.search(r'(\[|\().*', citation_raw)
        if match:
            citation_raw = match.group(0).strip()
            
    frontmatter = {
        "wpId": post_row["id"],
        "pubDate": pub_date,
        "lang": lang,
        "category": category_val,
        "slug": slug,
        "title": clean_title,
        "description": seo.get("meta_description", ""),
        "seoTitle": seo_title,
        "metaDescription": seo.get("meta_description", ""),
        "focusKeyphrase": seo.get("focus_keyphrase", ""),
        "longTailKeywords": seo.get("long_tail_keywords", []),
        "sourceOrigin": "migrated",
        "humanReviewed": True,
        "citation": citation_raw,
        "court": shared.get("court"),
        "claimant": shared.get("claimant"),
        "defendant": shared.get("defendant"),
        "courtLink": shared.get("courtLink"),
    }
    
    # None 값인 속성은 프론트매터에서 제거
    frontmatter = {k: v for k, v in frontmatter.items() if v is not None}
        
    # YAML 문자열로 변환 (allow_unicode=True 중요)
    yaml_str = yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)
    return f"---\n{yaml_str}---\n\n"

def publish_approved_posts():
    conn = get_db()
    approved_posts = conn.execute("SELECT * FROM posts WHERE status = 'approved'").fetchall()
    
    if not approved_posts:
        print("📭 발행할 글이 없습니다 (status='approved'인 글 0개).")
        conn.close()
        return

    ASTRO_POSTS_EN.mkdir(parents=True, exist_ok=True)
    ASTRO_POSTS_KO.mkdir(parents=True, exist_ok=True)

    success_count = 0
    for post in approved_posts:
        post_id = post["id"]
        slug = post["wp_slug"]
        out_dir = OUTPUT_BASE / slug
        
        meta_path = out_dir / "meta.yaml"
        en_path = out_dir / "en.md"
        ko_path = out_dir / "ko.md"
        
        if not (meta_path.exists() and en_path.exists() and ko_path.exists()):
            print(f"⚠️ [{slug}] 파일 누락으로 퍼블리싱 건너뜀 (en.md, ko.md, meta.yaml 확인 필요)")
            continue
            
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta_data = yaml.safe_load(f)
                
            import re
            def strip_frontmatter(md_content):
                if md_content.startswith("---"):
                    parts = md_content.split("---", 2)
                    if len(parts) >= 3:
                        return parts[2].lstrip()
                return md_content

            en_md_content = strip_frontmatter(en_path.read_text(encoding="utf-8"))
            ko_md_content = strip_frontmatter(ko_path.read_text(encoding="utf-8"))
            
            en_frontmatter = synthesize_frontmatter(post, meta_data, "en")
            ko_frontmatter = synthesize_frontmatter(post, meta_data, "ko")
            
            final_en = en_frontmatter + en_md_content
            final_ko = ko_frontmatter + ko_md_content
            
            (ASTRO_POSTS_EN / f"{slug}.md").write_text(final_en, encoding="utf-8")
            (ASTRO_POSTS_KO / f"{slug}.md").write_text(final_ko, encoding="utf-8")
            
            # DB 상태 업데이트
            conn.execute("UPDATE posts SET status = 'published' WHERE id = ?", (post_id,))
            conn.commit()
            
            print(f"✅ [{slug}] 퍼블리싱 완료")
            success_count += 1
            
            # 여기서 output-storage를 삭제할지 백업할지 결정 (일단 보존)
            backup_dir = out_dir.parent.parent / "published_backup" / slug
            backup_dir.parent.mkdir(parents=True, exist_ok=True)
            # shutil.move(out_dir, backup_dir) # 롤백을 위해 그냥 제자리에 두거나 백업 가능. 사용자 지시에 따라 "당분간 유지"
            
        except Exception as e:
            print(f"❌ [{slug}] 퍼블리싱 중 오류 발생: {e}")

    conn.close()
    print(f"\n🎉 총 {success_count}개 글 발행 완료!")

if __name__ == "__main__":
    publish_approved_posts()
