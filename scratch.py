import sys
from pathlib import Path
sys.path.insert(0, str(Path("migration/src").resolve()))
from migration.process import score_pdf_candidates

candidates = score_pdf_candidates("Partridge v Crittenden [1968] 2 All ER 421", "partridge-v-crittenden", "contract-law-cases,case-law")
for c in candidates[:5]:
    print(c)
