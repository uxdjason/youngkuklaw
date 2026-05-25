#!/usr/bin/env python3
"""
Font TTF → WOFF2 converter for YoungkukLaw project.
Converts selected fonts from references/fonts/ to public/fonts/
Korean fonts are subsetted to 2350 common Hangul characters + Basic Latin.
"""
import os
import sys
from pathlib import Path

# Minimum Korean unicode range: Hangul Syllables + Basic Latin + punctuation
KOREAN_SUBSET_UNICODES = (
    list(range(0x0020, 0x007F))   # Basic Latin
    + list(range(0x00A0, 0x00FF)) # Latin-1 Supplement
    + list(range(0xAC00, 0xD7A4)) # Hangul Syllables (가-힣, 11172 chars)
    + list(range(0x3130, 0x3190)) # Hangul Compatibility Jamo
)

BASE_DIR = Path(__file__).parent.parent
SRC_DIR = BASE_DIR / "references" / "fonts"
DEST_DIR = BASE_DIR / "public" / "fonts"
DEST_DIR.mkdir(parents=True, exist_ok=True)

def ttf_to_woff2(src: Path, dest: Path, subset_unicodes=None):
    from fontTools.ttLib import TTFont
    from fontTools.subset import Subsetter, Options
    
    font = TTFont(src)
    
    if subset_unicodes:
        options = Options()
        options.flavor = "woff2"
        options.desubroutinize = True
        subsetter = Subsetter(options=options)
        subsetter.populate(unicodes=subset_unicodes)
        subsetter.subset(font)
    
    font.flavor = "woff2"
    font.save(dest)
    size_kb = dest.stat().st_size // 1024
    print(f"  ✓ {dest.name} ({size_kb} KB)")

def convert_all():
    tasks = [
        # (src_relative, dest_name, is_korean)
        # --- Playfair (English Serif) ---
        ("Playfair/static/Playfair_9pt-Regular.ttf",      "Playfair-Regular.woff2",    False),
        ("Playfair/static/Playfair_9pt-Italic.ttf",       "Playfair-Italic.woff2",     False),
        ("Playfair/static/Playfair_9pt-Bold.ttf",         "Playfair-Bold.woff2",       False),
        ("Playfair/static/Playfair_9pt-BoldItalic.ttf",   "Playfair-BoldItalic.woff2", False),
        # --- Inter (English Sans-Serif) ---
        ("Inter/static/Inter_18pt-Regular.ttf",  "Inter-Regular.woff2",  False),
        ("Inter/static/Inter_18pt-Italic.ttf",   "Inter-Italic.woff2",   False),
        ("Inter/static/Inter_18pt-Medium.ttf",   "Inter-Medium.woff2",   False),
        ("Inter/static/Inter_18pt-Bold.ttf",     "Inter-Bold.woff2",     False),
        # --- Nanum Myeongjo (Korean Serif) ---
        ("Nanum_Myeongjo/NanumMyeongjo-Regular.ttf",   "NanumMyeongjo-Regular.woff2",   True),
        ("Nanum_Myeongjo/NanumMyeongjo-Bold.ttf",      "NanumMyeongjo-Bold.woff2",      True),
        ("Nanum_Myeongjo/NanumMyeongjo-ExtraBold.ttf", "NanumMyeongjo-ExtraBold.woff2", True),
        # --- Nanum Gothic (Korean Sans-Serif) ---
        ("Nanum_Gothic/NanumGothic-Regular.ttf",   "NanumGothic-Regular.woff2",   True),
        ("Nanum_Gothic/NanumGothic-Bold.ttf",      "NanumGothic-Bold.woff2",      True),
        ("Nanum_Gothic/NanumGothic-ExtraBold.ttf", "NanumGothic-ExtraBold.woff2", True),
    ]

    for src_rel, dest_name, is_korean in tasks:
        src = SRC_DIR / src_rel
        dest = DEST_DIR / dest_name
        if not src.exists():
            print(f"  ⚠ MISSING: {src}")
            continue
        print(f"Converting: {src.name} → {dest_name}")
        subset = KOREAN_SUBSET_UNICODES if is_korean else None
        ttf_to_woff2(src, dest, subset)

if __name__ == "__main__":
    print(f"Source: {SRC_DIR}")
    print(f"Destination: {DEST_DIR}\n")
    convert_all()
    print("\nDone.")
