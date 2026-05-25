import sqlite3
import os

os.makedirs('migration', exist_ok=True)
os.makedirs('pipeline', exist_ok=True)

# Migration DB
conn = sqlite3.connect('migration/state.db')
c = conn.cursor()
c.executescript("""
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    wp_slug TEXT NOT NULL,
    wp_url TEXT NOT NULL,
    wp_title_ko TEXT NOT NULL,
    wp_category TEXT NOT NULL,
    wp_pub_date TEXT NOT NULL,
    wp_modified_date TEXT,
    wp_html_path TEXT NOT NULL,
    wp_seo JSON,
    status TEXT NOT NULL DEFAULT 'pending',
    revision_scope TEXT,
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    sources JSON,
    research_json_path TEXT,
    output_dir TEXT,
    user_comment TEXT,
    revision_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_pubdate ON posts(wp_pub_date);

CREATE TABLE IF NOT EXISTS ai_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER REFERENCES posts(id),
    phase TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    tool_calls INTEGER DEFAULT 0,
    cost_usd REAL,
    latency_ms INTEGER,
    success BOOLEAN,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
""")
conn.commit()
conn.close()

# Pipeline DB
conn = sqlite3.connect('pipeline/state.db')
c = conn.cursor()
c.executescript("""
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    input_path TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    output_dir TEXT,
    parent_job_id INTEGER REFERENCES jobs(id),
    user_comment TEXT,
    revision_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS case_records (
    citation TEXT PRIMARY KEY,
    raw_citation TEXT NOT NULL,
    job_id INTEGER REFERENCES jobs(id),
    en_md_path TEXT,
    ko_md_path TEXT,
    published BOOLEAN DEFAULT 0,
    published_url_en TEXT,
    published_url_ko TEXT,
    pub_date TEXT
);

CREATE TABLE IF NOT EXISTS ai_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER REFERENCES posts(id),
    phase TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    tool_calls INTEGER DEFAULT 0,
    cost_usd REAL,
    latency_ms INTEGER,
    success BOOLEAN,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
""")
conn.commit()
conn.close()

print("Databases initialized successfully.")
