#!/usr/bin/env python3
"""
migration CLI 실행 wrapper.
사용법 (프로젝트 루트에서):
  python run_migration.py extract
  python run_migration.py extract --report
  python run_migration.py sources-status
  python run_migration.py status
"""
import sys
from pathlib import Path

# src 폴더를 Python 패스에 추가
sys.path.insert(0, str(Path(__file__).parent / "migration" / "src"))

from migration.cli import main

if __name__ == "__main__":
    main()
