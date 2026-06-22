import sys
import os
import re
import asyncio
import sqlite3
from pathlib import Path

# sys.path 등록 (migration 패키지 경로 탐색 해결)
src_dir = str(Path(__file__).resolve().parents[1])
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import streamlit as st
from bs4 import BeautifulSoup

from process import (
    DB_PATH, get_post, _update_status,
    score_pdf_candidates, process_post, OUTPUT_DIR
)

# ─────────────────────────────────────────────
# 기본 설정
# ─────────────────────────────────────────────
st.set_page_config(page_title="YoungkukLaw Migration Control Center", layout="wide")

# 세션 상태 초기화
if "selected_post_id" not in st.session_state:
    st.session_state.selected_post_id = None
if "is_processing" not in st.session_state:
    st.session_state.is_processing = False
if "process_error" not in st.session_state:
    st.session_state.process_error = None

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─────────────────────────────────────────────
# 사이드바: 카테고리별 Queue
# ─────────────────────────────────────────────
with st.sidebar:
    st.title("Migration Queue")

    conn = get_db()
    stats = conn.execute("SELECT status, COUNT(*) FROM posts GROUP BY status").fetchall()
    
    total = sum(r[1] for r in stats)
    approved = next((r[1] for r in stats if r[0] == "approved"), 0)
    st.progress(approved / total if total else 0, text=f"Approved: {approved} / {total}")

    status_icons = {
        "approved": "✅", "awaiting_review": "🟡", "pending": "⬜",
        "researching": "⏳", "failed": "❌", "awaiting_sources": "🔵", "published": "🌐"
    }
    for row in stats:
        icon = status_icons.get(row[0], "•")
        st.markdown(f"**{icon} {row[0]}** — **{row[1]}**")

    st.markdown("---")

    # 카테고리별 그룹화
    posts_all = conn.execute(
        "SELECT id, wp_slug, wp_category, wp_title_ko, status, wp_pub_date FROM posts "
        "ORDER BY wp_pub_date ASC"
    ).fetchall()
    conn.close()

    # 카테고리별 그룹화 + 정렬
    # 규칙: pending이 아닌 상태(작업 중/검수 대기 등)를 최상단, 나머지는 날짜 오름차순
    PRIORITY_STATUSES = {"awaiting_review", "researching", "writing_en", "writing_ko", "seo", "failed", "awaiting_sources"}

    grouped = {}
    for p in posts_all:
        cat = p['wp_category']
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(p)

    # 각 카테고리 내에서 정렬
    for cat in grouped:
        grouped[cat].sort(key=lambda p: (
            0 if p['status'] in PRIORITY_STATUSES else 1,  # 우선 상태 먼저
            p['wp_pub_date'] or ""                          # 그 다음 날짜 오름차순
        ))

    view_mode = st.radio("보기 옵션", ["발행 순서대로 보기", "카테고리별 보기"], index=0)
    
    if view_mode == "카테고리별 보기":
        st.markdown("### Select a Post by Category")
        for cat, cat_posts in grouped.items():
            with st.expander(f"📁 {cat} ({len(cat_posts)})"):
                for p in cat_posts:
                    icon = {"pending": "⬜", "awaiting_review": "🟡", "approved": "✅",
                            "failed": "❌", "researching": "⏳", "awaiting_sources": "🔵", "published": "🌐"}.get(p["status"], "⬜")
                    label = f"{icon} {p['wp_title_ko']}"
                    if st.button(label, key=f"btn_cat_{p['id']}", use_container_width=True):
                        st.session_state.selected_post_id = p['id']
                        st.session_state.is_processing = False
                        st.session_state.process_error = None
                        st.rerun()
    else:
        st.markdown("### 발행 순서대로 보기")
        with st.expander(f"전체 글 ({len(posts_all)})", expanded=True):
            for p in posts_all:
                icon = {"pending": "⬜", "awaiting_review": "🟡", "approved": "✅",
                        "failed": "❌", "researching": "⏳", "awaiting_sources": "🔵"}.get(p["status"], "⬜")
                label = f"{icon} {p['wp_title_ko']}"
                if st.button(label, key=f"btn_all_{p['id']}", use_container_width=True):
                    st.session_state.selected_post_id = p['id']
                    st.session_state.is_processing = False
                    st.session_state.process_error = None
                    st.rerun()

# ─────────────────────────────────────────────
# 메인 영역
# ─────────────────────────────────────────────
if st.session_state.selected_post_id is None:
    st.info("👈 좌측 사이드바에서 카테고리를 펼쳐 글을 선택하십시오.")
    st.stop()

selected_post_id = st.session_state.selected_post_id
post = get_post(selected_post_id)
if not post:
    st.error("Post not found in DB. Please select another post.")
    st.session_state.selected_post_id = None
    st.stop()

slug = post["wp_slug"]
# DB에서 항상 최신 상태를 다시 읽음
conn2 = get_db()
current_status = conn2.execute("SELECT status FROM posts WHERE id=?", (selected_post_id,)).fetchone()["status"]
conn2.close()

categories = post["wp_category"]
title = post["wp_title_ko"]

col1, col2 = st.columns([7, 3])
with col1:
    st.title(title)
    st.markdown(f"**Slug:** `{slug}` &nbsp;|&nbsp; **Category:** `{categories}` &nbsp;|&nbsp; **Status:** `{current_status}`")
with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    migration_mode = st.radio(
        "마이그레이션 모드", 
        ["기존 WP 우선 모드", "대폭 개선 옵션"], 
        index=0, 
        horizontal=True,
        label_visibility="collapsed",
        key=f"mode_{selected_post_id}"
    )
st.markdown("---")

# WP 원문 텍스트 파싱
wp_html_path = post["wp_html_path"]
wp_text = ""
if wp_html_path and Path(wp_html_path).exists():
    html = Path(wp_html_path).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    wp_text = soup.get_text(separator="\n").strip()
    wp_text = re.sub(r'\n{3,}', '\n\n', wp_text)

# ─────────────────────────────────────────────
# 2단 레이아웃
# ─────────────────────────────────────────────
col_left, col_right = st.columns([4, 6], gap="large")

with col_left:
    st.subheader("📝 WP Original Text (Korean)")
    st.markdown(
        f"""<div style="height: calc(100vh - 180px); overflow-y: auto; padding: 16px;
                border: 1px solid #dee2e6; border-radius: 8px;
                background: #fff; color: #212529;
                font-size: 15px; line-height: 1.7; white-space: pre-wrap;">{wp_text}</div>""",
        unsafe_allow_html=True,
    )

with col_right:
    # ── 처리 중 상태 표시 ──────────────────────────────────
    if current_status in ("researching", "writing_en", "writing_ko", "seo"):
        # DB에서 updated_at 읽기
        conn3 = get_db()
        row = conn3.execute("SELECT status, updated_at FROM posts WHERE id=?", (selected_post_id,)).fetchone()
        conn3.close()

        step_labels = {
            "researching": ("1/4", "📚 PDF 분석 및 법리 리서치 중"),
            "writing_en":  ("2/4", "✍️  영문 본문 작성 중"),
            "writing_ko":  ("3/4", "✍️  한국어 본문 작성 중"),
            "seo":         ("4/4", "🔖 SEO 메타 데이터 생성 중"),
        }
        step_num, step_label = step_labels.get(row["status"], ("?", row["status"]))

        # 경과 시간 계산
        elapsed_str = ""
        if row["updated_at"]:
            from datetime import datetime, timezone
            try:
                updated = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                elapsed = int((now - updated).total_seconds())
                mins, secs = divmod(elapsed, 60)
                elapsed_str = f"{mins}분 {secs}초" if mins else f"{secs}초"
            except Exception:
                pass

        progress_val = {"researching": 0.15, "writing_en": 0.40, "writing_ko": 0.65, "seo": 0.90}.get(row["status"], 0.1)
        st.progress(progress_val, text=f"Step {step_num} — {step_label}")
        st.markdown(f"현재 단계에서 경과 시간: **{elapsed_str}** (이 단계 시작 이후)")
        
        # progress.log 내용 읽어서 표시
        from pathlib import Path
        log_path = Path("output-storage/migration") / slug / "progress.log"
        if log_path.exists():
            log_content = log_path.read_text(encoding="utf-8")
            st.code(log_content, language="bash")
        
        st.caption("새로고침을 눌러 현 상태를 업데이트할 수 있습니다.")

        col_r, col_c = st.columns([1, 1])
        with col_r:
            if st.button("🔄 새로고침", use_container_width=True):
                st.rerun()
        with col_c:
            if st.button("❌ 작업 취소 (pending으로 되돌리기)", use_container_width=True):
                _update_status(selected_post_id, "pending")
                st.success("작업을 취소하고 pending 상태로 복원했습니다.")
                st.rerun()
        st.stop()

    # ── VIEW 1: 소스 지정 및 실행 ─────────────────────────
    elif current_status in ("pending", "awaiting_sources", "failed"):
        st.header("⚙️ Step 1: Source Selection & Generation")

        # 에러 메시지 표시
        if st.session_state.process_error:
            st.error(f"Migration Failed: {st.session_state.process_error}")
            st.session_state.process_error = None

        st.subheader("Auto-Suggested PDFs from `law-sources`")
        candidates = score_pdf_candidates(title, slug, categories)
        selected_candidate_paths = []

        if candidates:
            for c in candidates[:5]:
                if st.checkbox(
                    f"[{c['folder']}] {c['filename']} (Score: {c['score']:.1f})",
                    key=f"chk_{c['path']}"
                ):
                    selected_candidate_paths.append(c['path'])
        else:
            st.info("관련 PDF를 자동으로 찾지 못했습니다. 아래에서 직접 경로를 입력하십시오.")

        st.subheader("Additional Sources & Instructions")
        manual_pdfs = st.text_input(
            "Additional PDF Paths (comma separated, absolute paths)",
            key=f"manual_pdf_{selected_post_id}"
        )
        manual_urls = st.text_input(
            "Web URLs for Reference (comma separated)",
            key=f"manual_url_{selected_post_id}"
        )
        user_instructions = st.text_area(
            "Specific Instructions for AI (Optional)",
            placeholder="E.g., Focus on the ratio of the majority judgment.",
            key=f"inst_{selected_post_id}"
        )

        if st.button("🚀 Run Migration", use_container_width=True, key="run_btn"):
            final_pdfs = list(selected_candidate_paths)
            if manual_pdfs.strip():
                final_pdfs.extend([p.strip() for p in manual_pdfs.split(",") if p.strip()])
            final_urls = [u.strip() for u in manual_urls.split(",") if u.strip()] if manual_urls.strip() else []

            missing = [p for p in final_pdfs if not Path(p).exists()]
            if missing:
                st.error(f"파일을 찾을 수 없습니다: {missing}")
            else:
                import threading
                import time
                def run_in_bg(post_id, pdfs, urls, inst, mode):
                    import asyncio
                    try:
                        asyncio.run(process_post(
                            post_id=post_id,
                            pdf_paths=pdfs,
                            web_urls=urls,
                            user_instructions=inst,
                            mode=mode,
                            verbose=False,
                        ))
                    except Exception as e:
                        import traceback
                        print(f"Background thread error: {e}")
                        traceback.print_exc()

                threading.Thread(
                    target=run_in_bg,
                    args=(selected_post_id, final_pdfs, final_urls, user_instructions.strip(), migration_mode),
                    daemon=True
                ).start()
                
                # DB 업데이트를 위해 아주 잠깐 대기한 후 새로고침
                time.sleep(0.3)
                st.rerun()

    # ── VIEW 2: 검수 및 승인 ───────────────────────────────
    elif current_status in ("awaiting_review", "approved", "published"):
        st.header("✅ Step 2: Review & Approve")

        out_dir = Path(OUTPUT_DIR) / "migration" / slug
        en_path = out_dir / "en.md"
        ko_path = out_dir / "ko.md"
        meta_path = out_dir / "meta.yaml"
        research_path = out_dir / "reference" / "web_research.md"

        def split_frontmatter(text: str) -> tuple[dict, str]:
            import yaml as _yaml
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    try:
                        fm = _yaml.safe_load(parts[1]) or {}
                        return fm, parts[2].strip()
                    except Exception:
                        pass
            return {}, text

        en_raw = en_path.read_text(encoding="utf-8") if en_path.exists() else "*Not found*"
        ko_raw = ko_path.read_text(encoding="utf-8") if ko_path.exists() else "*Not found*"
        meta_text = meta_path.read_text(encoding="utf-8") if meta_path.exists() else "{}"
        research_text = research_path.read_text(encoding="utf-8") if research_path.exists() else "No research file."

        en_fm, en_body = split_frontmatter(en_raw)
        ko_fm, ko_body = split_frontmatter(ko_raw)

        tab_en, tab_ko, tab_seo, tab_meta = st.tabs(
            ["Draft (EN)", "Draft (KO)", "SEO Preview", "Meta Data"]
        )

        with tab_en:
            edited_en = st.text_area(
                "영문 본문 직접 편집 가능 (수정 후 Save 클릭)",
                value=en_body,
                height=680,
                key=f"edit_en_{selected_post_id}",
            )
            if st.button("💾 Save EN Draft", key="save_en"):
                # 프론트매터 재결합 후 저장
                fm_str = "---\n" + "\n".join(
                    f"{k}: {repr(v) if isinstance(v, str) else v}"
                    for k, v in en_fm.items()
                ) if en_fm else ""
                new_content = (f"{fm_str}\n---\n\n" if en_fm else "") + edited_en
                en_path.write_text(new_content, encoding="utf-8")
                st.success("EN Draft 저장 완료!")

        with tab_ko:
            edited_ko = st.text_area(
                "한국어 본문 직접 편집 가능 (수정 후 Save 클릭)",
                value=ko_body,
                height=680,
                key=f"edit_ko_{selected_post_id}",
            )
            if st.button("💾 Save KO Draft", key="save_ko"):
                fm_str = "---\n" + "\n".join(
                    f"{k}: {repr(v) if isinstance(v, str) else v}"
                    for k, v in ko_fm.items()
                ) if ko_fm else ""
                new_content = (f"{fm_str}\n---\n\n" if ko_fm else "") + edited_ko
                ko_path.write_text(new_content, encoding="utf-8")
                st.success("KO Draft 저장 완료!")

        with tab_seo:
            st.markdown("### 🔍 SEO 메타데이터 검수")
            st.caption("아래 내용이 검색 결과에 표시됩니다. 내용이 자연스러운지 확인하십시오.")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.markdown("**🇬🇧 English**")
                st.markdown(f"**Title:** {en_fm.get('seoTitle', en_fm.get('title', ''))}")
                st.markdown(f"**Description:** {en_fm.get('metaDescription', en_fm.get('description', ''))}")
                st.markdown(f"**Focus Keyphrase:** `{en_fm.get('focusKeyphrase', '')}`")
                kws = en_fm.get('longTailKeywords', [])
                if kws:
                    st.markdown("**Long-tail Keywords:**")
                    for kw in kws:
                        st.markdown(f"- {kw}")
            with col_s2:
                st.markdown("**🇰🇷 Korean**")
                st.markdown(f"**Title:** {ko_fm.get('seoTitle', ko_fm.get('title', ''))}")
                st.markdown(f"**Description:** {ko_fm.get('metaDescription', ko_fm.get('description', ''))}")
                st.markdown(f"**Focus Keyphrase:** `{ko_fm.get('focusKeyphrase', '')}`")
                kws_ko = ko_fm.get('longTailKeywords', [])
                if kws_ko:
                    st.markdown("**Long-tail Keywords:**")
                    for kw in kws_ko:
                        st.markdown(f"- {kw}")
                        
            st.markdown("---")
            st.markdown("#### 📄 실제 페이지 H1 타이틀 (미리보기)")
            st.caption("위의 SEO Title과 별개로 실제 판례 글 상단에 H1으로 노출될 정제된 이름입니다.")
            
            # publish.py와 동일한 H1 타이틀 추출 로직 시뮬레이션
            title_raw = post["wp_title_ko"]
            clean_title = title_raw
            if "case" in post["wp_category"]:
                import re
                match = re.split(r'\[|\(', title_raw)
                if match:
                    clean_title = match[0].strip()
            st.markdown(f"**{clean_title}**")

        # Case metadata preview (only for case law)
        is_case_post = "case" in post["wp_category"]
        if is_case_post:
            st.markdown("---")
            st.markdown("#### ⚖️ 판례 헤더 메타데이터")
            st.caption("아래 정보는 본문이 아닌 판례 페이지 상단 헤더 영역에 표시됩니다. 빈칸이 있으면 재작업이 필요합니다.")
            
            # Citation 정제 로직 시뮬레이션 (publish.py와 동일)
            citation_raw = en_fm.get('citation', '')
            if citation_raw and ("[" in citation_raw or "(" in citation_raw):
                import re
                match = re.search(r'(\[|\().*', citation_raw)
                if match:
                    citation_raw = match.group(0).strip()
            
            meta_col1, meta_col2 = st.columns(2)
            with meta_col1:
                st.markdown(f"**Citation:** {citation_raw or '❌ 없음'}")
                st.markdown(f"**Court:** {en_fm.get('court', '❌ 없음')}")
            with meta_col2:
                c_role = en_fm.get('claimantRole') or 'Claimant'
                d_role = en_fm.get('defendantRole') or 'Defendant'
                st.markdown(f"**{c_role}:** {en_fm.get('claimant', '❌ 없음')}")
                st.markdown(f"**{d_role}:** {en_fm.get('defendant', '❌ 없음')}")

            # CourtLink 편집 필드
            current_court_link = en_fm.get("courtLink", "")
            new_court_link = st.text_input(
                "🔗 Citation URL (WP 원본 링크, 필요 시 변경 가능)",
                value=current_court_link,
                placeholder="https://...",
                key=f"court_link_{selected_post_id}",
            )
            if st.button("💾 Citation URL 저장", key="save_court_link"):
                import yaml as _yaml
                def _update_fm_field(md_text: str, field: str, value: str) -> str:
                    if md_text.startswith("---"):
                        parts = md_text.split("---", 2)
                        if len(parts) >= 3:
                            fm_data = _yaml.safe_load(parts[1]) or {}
                            fm_data[field] = value
                            new_yaml = _yaml.dump(fm_data, allow_unicode=True, sort_keys=False, default_flow_style=False)
                            return f"---\n{new_yaml}---\n\n{parts[2].strip()}"
                    return md_text
                for md_path in (en_path, ko_path):
                    if md_path.exists():
                        md_path.write_text(
                            _update_fm_field(md_path.read_text(encoding="utf-8"), "courtLink", new_court_link),
                            encoding="utf-8"
                        )
                st.success("Citation URL 저장 완료!")

        with tab_meta:
            st.code(meta_text, language="yaml")

        with st.expander("📋 AI Research Notes (참고용 — 발행 글에 포함되지 않음)"):
            st.caption("AI가 리서치 단계에서 사용한 근거 자료 로그입니다. 검수 대상이 아니며, 결과물의 근거를 역추적할 때만 확인하십시오.")
            st.markdown(research_text)

        st.markdown("---")

        if current_status == "awaiting_review":
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                if st.button("✅ Approve & Publish", use_container_width=True):
                    _update_status(selected_post_id, "approved")
                    from migration.publish import publish_approved_posts
                    publish_approved_posts()
                    st.success("승인 및 퍼블리시 완료!")
                    st.rerun()
            with col_b:
                with st.expander("✏️ 재작업 요청"):
                    revise_comment = st.text_area("수정 지시사항을 입력하십시오.")
                    if st.button("재작업 요청 제출"):
                        _update_status(selected_post_id, "failed", f"Revision: {revise_comment}")
                        st.warning("재작업 큐로 돌려보냈습니다.")
                        st.rerun()
            with col_c:
                if st.button("🔄 Pending으로 되돌리기", use_container_width=True, type="secondary"):
                    _update_status(selected_post_id, "pending")
                    st.warning("Pending 상태로 초기화했습니다. 처음부터 다시 시작할 수 있습니다.")
                    st.rerun()
        else:
            st.success(f"이 글은 현재 **{current_status}** 상태입니다.")
            col_ap1, col_ap2 = st.columns(2)
            with col_ap1:
                if st.button("⏪ 승인/발행 취소 (Revert to Review)", use_container_width=True):
                    _update_status(selected_post_id, "awaiting_review")
                    st.rerun()
            with col_ap2:
                if st.button("🔄 Pending으로 되돌리기", use_container_width=True, type="secondary", key="reset_approved"):
                    _update_status(selected_post_id, "pending")
                    st.warning("Pending 상태로 초기화했습니다. 처음부터 다시 시작할 수 있습니다.")
                    st.rerun()
    else:
        st.warning(f"알 수 없는 상태: `{current_status}`. 사이드바에서 다른 글을 선택하십시오.")
