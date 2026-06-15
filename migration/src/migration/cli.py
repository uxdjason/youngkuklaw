"""
cli.py — migration 패키지 CLI 진입점

사용법:
  python -m migration extract [--xml <path>] [--db <path>] [--output <dir>]
  python -m migration extract --report
  python -m migration sources-status
  python -m migration status
"""

import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv()

# 프로젝트 루트 (cli.py 기준)
# migration/src/migration/cli.py
# parents[0] = migration/src/migration/
# parents[1] = migration/src/
# parents[2] = migration/
# parents[3] = YoungkukLaw/ (프로젝트 루트)
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_XML = os.getenv("WP_EXPORT_PATH", str(PROJECT_ROOT / "legacy-source/wordpress-export/youngkuklaw.WordPress.xml"))
DEFAULT_DB = str(PROJECT_ROOT / "migration/state.db")
DEFAULT_OUTPUT = str(PROJECT_ROOT / "output-storage")
DEFAULT_REPORTS = str(PROJECT_ROOT / "migration/reports")
DEFAULT_SOURCES = str(PROJECT_ROOT / "migration-sources")


def cmd_extract(args: argparse.Namespace) -> None:
    from migration.wp_extract import extract_all, generate_reports

    if args.report_only:
        print("📊 보고서만 재생성합니다...")
        generate_reports(
            db_path=args.db,
            reports_dir=args.reports,
            migration_sources_dir=args.sources,
        )
        return

    print("🚀 WordPress 데이터 추출을 시작합니다")
    print(f"   XML: {args.xml}")
    print(f"   DB:  {args.db}")
    print(f"   출력: {args.output}")

    inserted = extract_all(
        xml_path=args.xml,
        db_path=args.db,
        output_dir=args.output,
        reports_dir=args.reports,
        migration_sources_dir=args.sources,
    )
    print(f"\n🎉 Phase 3 추출 완료! {inserted}개 새 글이 DB에 추가됨.")
    print(f"   보고서: {args.reports}/extract_report.md")
    print(f"   체크리스트: {args.reports}/source_notes_checklist.md")


def cmd_sources_status(args: argparse.Namespace) -> None:
    from migration.wp_extract import sources_status
    sources_status(db_path=args.db, migration_sources_dir=args.sources)


def cmd_status(args: argparse.Namespace) -> None:
    import sqlite3
    conn = sqlite3.connect(args.db)
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM posts GROUP BY status ORDER BY cnt DESC"
    ).fetchall()
    conn.close()
    total = sum(r[1] for r in rows)
    print(f"\n{'상태':<25} {'글 수':>8}")
    print("-" * 35)
    for status, cnt in rows:
        print(f"{status:<25} {cnt:>8}")
    print("-" * 35)
    print(f"{'합계':<25} {total:>8}")


def cmd_process(args: argparse.Namespace) -> None:
    """단건 처리 (디버그용)."""
    import asyncio
    from migration.process import process_post

    revision_scope = args.revision if hasattr(args, "revision") else None
    print(f"🔧 단건 처리: post_id={args.post_id}, revision_scope={revision_scope}")
    asyncio.run(process_post(args.post_id, revision_scope=revision_scope))


def cmd_run(args: argparse.Namespace) -> None:
    """전체 큐 실행 (소스 준비된 글만)."""
    import asyncio
    from migration.process import run_queue

    limit = args.limit if hasattr(args, "limit") and args.limit else None
    print(f"🏃 큐 러너 시작: workers={args.workers}, limit={limit or '전체'}")
    asyncio.run(run_queue(workers=args.workers, limit=limit))


def cmd_resolve_sources(args: argparse.Namespace) -> None:
    """
    법률 소스 PDF를 글별로 확인하는 인터랙티브 단계.

    흐름 (글 1건당):
      1. law-sources/ 에서 후보 PDF를 점수 기반으로 탐색
      2. 후보 목록을 표시
      3. 사용자가 번호 선택 / 경로 직접 입력 / 건너뜀 / web search 선택
      4. confirmed_pdfs.yaml 저장
    """
    import sqlite3 as _sqlite3
    from migration.process import (
        score_pdf_candidates,
        save_confirmed_sources,
        load_confirmed_sources,
        SOURCES_DIR,
    )

    db_path = args.db

    # 처리 대상 글 목록 결정
    conn = _sqlite3.connect(db_path)
    conn.row_factory = _sqlite3.Row

    if args.post_id:
        rows = conn.execute(
            "SELECT id, wp_slug, wp_title_ko, wp_category FROM posts WHERE id=?",
            (args.post_id,)
        ).fetchall()
    else:
        # pending 글 중 notes.md 있는 것만, 발행일 오래된 순
        rows = conn.execute(
            "SELECT id, wp_slug, wp_title_ko, wp_category FROM posts "
            "WHERE status IN ('pending','awaiting_sources') ORDER BY wp_pub_date ASC"
        ).fetchall()
    conn.close()

    if not rows:
        print("📭 확인할 글이 없습니다.")
        return

    # notes.md 있는 것만 필터
    from pathlib import Path
    filtered = []
    for row in rows:
        notes = Path(SOURCES_DIR) / row["wp_slug"] / "notes.md"
        if notes.exists():
            filtered.append(row)

    if not filtered:
        print("📭 소스 노트(notes.md)가 준비된 글이 없습니다.")
        return

    # 이미 확인된 것 제외 (--all 옵션 없을 때)
    if not args.all:
        pending_confirm = []
        for row in filtered:
            if load_confirmed_sources(row["wp_slug"]) is None:
                pending_confirm.append(row)
        if not pending_confirm:
            print("✅ 모든 글의 PDF 소스가 이미 확인되었습니다.")
            return
        filtered = pending_confirm

    total = len(filtered)
    print(f"\n{'='*60}")
    print(f"📋 PDF 소스 확인: {total}개 글")
    print(f"   (건너뛰려면 'skip', 종료하려면 'quit' 입력)")
    print(f"{'='*60}\n")

    confirmed_count = 0
    skipped_count = 0

    for idx, row in enumerate(filtered, 1):
        slug = row["wp_slug"]
        title = row["wp_title_ko"]
        categories = row["wp_category"]

        print(f"\n[{idx}/{total}] {title}")
        print(f"  Slug     : {slug}")
        print(f"  Category : {categories}")
        print()

        # 후보 탐색
        candidates = score_pdf_candidates(title, slug, categories)

        if not candidates:
            print("  🔍 law-sources/에서 후보 PDF를 찾지 못했습니다.")
            print("  선택:")
            print("    p = 경로 직접 입력")
            print("    w = web search 사용 (PDF 없이 진행)")
            print("    skip = 이 글 건너뜀")
            print("    quit = 여기서 종료")
        else:
            print(f"  📄 후보 PDF ({len(candidates)}개, 점수 높은 순):")
            # 상위 10개만 표시
            show = candidates[:10]
            for i, c in enumerate(show, 1):
                bar = "█" * int(c["score"] / 10)
                terms = ", ".join(c["matched_terms"][:5]) if c["matched_terms"] else "—"
                print(f"    [{i}] (점수 {c['score']:>5.1f}) [{c['folder']}] {c['filename']}")
                print(f"         매칭 키워드: {terms}")
            if len(candidates) > 10:
                print(f"       ... 외 {len(candidates) - 10}개 (더 보려면 'more' 입력)")
            print()
            print("  선택:")
            print("    번호 (예: 1 또는 1 3) = 해당 PDF 사용")
            print("    p = 경로 직접 입력")
            print("    w = web search 사용 (PDF 없이 진행)")
            print("    skip = 이 글 건너뜀")
            print("    quit = 여기서 종료")
            print("    more = 나머지 후보 모두 표시")

        while True:
            try:
                raw = input("\n  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n종료합니다.")
                return

            if raw == "quit":
                print(f"\n중단. 확인 완료: {confirmed_count}개 | 건너뜀: {skipped_count}개")
                return

            if raw == "skip":
                skipped_count += 1
                print(f"  ⏭️  건너뜀: {slug}")
                break

            if raw == "w":
                save_confirmed_sources(slug, [], use_web_supplement=False)
                confirmed_count += 1
                print(f"  🌐 web search 모드로 저장: {slug}")
                break

            if raw == "p":
                path_raw = input("  PDF 경로 (여러 개는 쉼표로 구분): ").strip()
                paths = [p.strip().strip("'\"") for p in path_raw.split(",") if p.strip()]
                valid = [p for p in paths if Path(p).exists()]
                if not valid:
                    print("  ❌ 유효한 경로가 없습니다. 다시 입력하세요.")
                    continue
                web_sup = input("  웹검색 보완 사용? (최신 업데이트 확인용) [y/n, 기본 y]: ").strip().lower()
                use_web_sup = web_sup != "n"
                save_confirmed_sources(slug, valid, use_web_supplement=use_web_sup)
                confirmed_count += 1
                print(f"  ✅ 저장 완료 ({len(valid)}개 PDF): {slug}")
                break

            if raw == "more" and candidates:
                for i, c in enumerate(candidates, 1):
                    bar = "█" * int(c["score"] / 10)
                    print(f"    [{i}] (점수 {c['score']:>5.1f}) [{c['folder']}] {c['filename']}")
                continue

            # 번호 선택
            try:
                nums = [int(n) for n in raw.split()]
                selected_paths = []
                for n in nums:
                    if 1 <= n <= len(candidates):
                        selected_paths.append(candidates[n-1]["path"])
                    else:
                        print(f"  ❌ 잘못된 번호: {n}")
                        selected_paths = []
                        break
                if not selected_paths:
                    continue

                # 선택 확인 표시
                print(f"\n  선택된 PDF:")
                for p in selected_paths:
                    print(f"    • {Path(p).name}")
                web_sup = input("  웹검색 보완 사용? (최신 업데이트 확인용) [y/n, 기본 y]: ").strip().lower()
                use_web_sup = web_sup != "n"

                confirm = input(f"  이 소스로 확정합니까? [y/n]: ").strip().lower()
                if confirm == "y":
                    save_confirmed_sources(slug, selected_paths, use_web_supplement=use_web_sup)
                    confirmed_count += 1
                    print(f"  ✅ 확정: {slug}")
                    break
                else:
                    print("  다시 선택하세요.")
                    continue
            except ValueError:
                print("  ❓ 이해하지 못했습니다. 번호, p, w, skip, quit 중 하나를 입력하세요.")

    print(f"\n{'='*60}")
    print(f"🎉 소스 확인 완료: {confirmed_count}개 확정 | {skipped_count}개 건너뜀")
    print(f"   이제 처리를 시작하세요: python run_migration.py run --workers 4")
    print(f"{'='*60}")





def main() -> None:
    parser = argparse.ArgumentParser(
        prog="migration",
        description="YoungkukLaw 마이그레이션 CLI",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite DB 경로")
    parser.add_argument("--sources", default=DEFAULT_SOURCES, help="migration-sources/ 경로")
    parser.add_argument("--reports", default=DEFAULT_REPORTS, help="reports/ 출력 경로")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # extract 서브커맨드
    extract_parser = subparsers.add_parser("extract", help="WP XML에서 데이터 추출")
    extract_parser.add_argument("--xml", default=DEFAULT_XML, help="WordPress XML 경로")
    extract_parser.add_argument("--output", default=DEFAULT_OUTPUT, help="output-storage 경로")
    extract_parser.add_argument("--report", dest="report_only", action="store_true", help="보고서만 재생성")

    # sources-status 서브커맨드
    subparsers.add_parser("sources-status", help="migration-sources/ 준비 현황")

    # status 서브커맨드
    subparsers.add_parser("status", help="DB 상태 요약")

    # process 서브커맨드 (단건 처리)
    process_parser = subparsers.add_parser("process", help="글 1건 처리 (post-id 지정)")
    process_parser.add_argument("--post-id", type=int, required=True, dest="post_id", help="처리할 post ID")
    process_parser.add_argument("--revision", choices=["full", "write_only", "seo_only"],
                                default=None, help="재시도 범위 (기본: 처음부터)")

    # run 서브커맨드 (전체 큐)
    run_parser = subparsers.add_parser("run", help="소스 준비된 글 전체 처리 (큐 러너)")
    run_parser.add_argument("--workers", type=int, default=4, help="동시 처리 수 (기본: 4)")
    run_parser.add_argument("--limit", type=int, default=None, help="최대 처리 글 수 (기본: 전체)")

    # ui 서브커맨드 (통합 마이그레이션 앱)
    subparsers.add_parser(
        "ui",
        help="Streamlit 기반 통합 마이그레이션 UI 실행",
    )

    args = parser.parse_args()

    if args.command == "extract":
        cmd_extract(args)
    elif args.command == "sources-status":
        cmd_sources_status(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "process":
        cmd_process(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "ui":
        import os
        import sys
        from pathlib import Path
        ui_path = Path(__file__).parent / "ui_app.py"
        os.system(f"{sys.executable} -m streamlit run {ui_path}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
