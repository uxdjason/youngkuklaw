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
        "researching": "⏳", "failed": "❌", "awaiting_sources": "🔵",
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

    st.markdown("### Select a Post by Category")
    for cat, cat_posts in grouped.items():
        with st.expander(f"📁 {cat} ({len(cat_posts)})"):
            for p in cat_posts:
                # 상태별 색상 아이콘
                icon = {"pending": "⬜", "awaiting_review": "🟡", "approved": "✅",
                        "failed": "❌", "researching": "⏳", "awaiting_sources": "🔵"}.get(p["status"], "⬜")
                label = f"{icon} {p['wp_title_ko']}"
                if st.button(label, key=f"btn_{p['id']}", use_container_width=True):
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

st.title(title)
st.markdown(f"**Slug:** `{slug}` &nbsp;|&nbsp; **Category:** `{categories}` &nbsp;|&nbsp; **Status:** `{current_status}`")
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
                with st.spinner("AI 처리 중... 몇 분이 소요될 수 있습니다."):
                    try:
                        result = asyncio.run(process_post(
                            post_id=selected_post_id,
                            pdf_paths=final_pdfs,
                            web_urls=final_urls,
                            user_instructions=user_instructions.strip(),
                            verbose=False,
                        ))
                        st.success(f"완료: {result}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Migration Failed: {e}")

    # ── VIEW 2: 검수 및 승인 ───────────────────────────────
    elif current_status in ("awaiting_review", "approved"):
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

        with tab_meta:
            st.code(meta_text, language="yaml")

        with st.expander("📋 AI Research Notes (참고용 — 발행 글에 포함되지 않음)"):
            st.caption("AI가 리서치 단계에서 사용한 근거 자료 로그입니다. 검수 대상이 아니며, 결과물의 근거를 역추적할 때만 확인하십시오.")
            st.markdown(research_text)

        st.markdown("---")

        if current_status == "awaiting_review":
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✅ Approve Post", use_container_width=True):
                    _update_status(selected_post_id, "approved")
                    st.success("승인 완료!")
                    st.rerun()
            with col_b:
                with st.expander("✏️ 재작업 요청"):
                    revise_comment = st.text_area("수정 지시사항을 입력하십시오.")
                    if st.button("재작업 요청 제출"):
                        _update_status(selected_post_id, "failed", f"Revision: {revise_comment}")
                        st.warning("재작업 큐로 돌려보냈습니다.")
                        st.rerun()
        else:
            st.success("이 글은 이미 승인(APPROVED) 상태입니다.")
            if st.button("승인 취소 (검수 화면으로 복귀)"):
                _update_status(selected_post_id, "awaiting_review")
                st.rerun()
    else:
        st.warning(f"알 수 없는 상태: `{current_status}`. 사이드바에서 다른 글을 선택하십시오.")
