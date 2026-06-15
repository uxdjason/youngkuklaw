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

    args = parser.parse_args()

    if args.command == "extract":
        cmd_extract(args)
    elif args.command == "sources-status":
        cmd_sources_status(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
