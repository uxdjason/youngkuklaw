import re
import sqlite3

def _get_all_valid_slugs() -> set[str]:
    conn = sqlite3.connect("migration/state.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT wp_slug FROM posts").fetchall()
    conn.close()
    return {r["wp_slug"] for r in rows if r["wp_slug"]}

def _enforce_valid_links(text: str, current_slug: str) -> str:
    valid_slugs = _get_all_valid_slugs()
    def replace_link(match):
        link_text = match.group(1)
        url = match.group(2).strip()
        if url.startswith("http://") or url.startswith("https://") or url.startswith("mailto:"):
            return match.group(0)
        slug = url.split("#")[0].split("?")[0].strip("/")
        if slug.startswith("ko/"):
            slug = slug[3:]
        elif slug.startswith("en/"):
            slug = slug[3:]
        slug = slug.strip("/")
        if not slug or slug not in valid_slugs or slug == current_slug:
            return link_text
        return match.group(0)
    pattern = re.compile(r'\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(([^)\s]+)\)')
    return pattern.sub(replace_link, text)

valid_slugs = _get_all_valid_slugs()
print(f"Total valid slugs: {len(valid_slugs)}")
print(f"entick-v-carrington in valid slugs: {'entick-v-carrington' in valid_slugs}")
print(f"unison-v-lord-chancellor in valid slugs: {'unison-v-lord-chancellor' in valid_slugs}")
print(f"fake-case in valid slugs: {'fake-case' in valid_slugs}")

text = "See [Unison [2017]](/unison-v-lord-chancellor) and [Fake](/fake-case) and [Entick](/ko/entick-v-carrington)."
print("Result:", _enforce_valid_links(text, "entick-v-carrington"))

