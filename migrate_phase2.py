#!/usr/bin/env python3
"""Database migration for Phase 2 features.

Run this against an existing footprint.db to add Phase 2 tables and columns.
Safe to run multiple times (idempotent).

Usage:
    python migrate_phase2.py [path/to/footprint.db]
"""

import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = "data/footprint.db"

# Each statement is tried independently; "duplicate column" errors are silently ignored.
MIGRATIONS = [
    # -- crawl_sessions: fingerprinting columns --
    "ALTER TABLE crawl_sessions ADD COLUMN fp_severity TEXT",
    "ALTER TABLE crawl_sessions ADD COLUMN fp_event_count INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN fp_canvas BOOLEAN DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN fp_webgl BOOLEAN DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN fp_audio BOOLEAN DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN fp_font BOOLEAN DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN fp_navigator BOOLEAN DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN fp_storage BOOLEAN DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN fp_unique_apis INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN fp_unique_entities INTEGER DEFAULT 0",
    # -- crawl_sessions: ad detection columns --
    "ALTER TABLE crawl_sessions ADD COLUMN ad_count INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN ad_visible_count INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN ad_density REAL DEFAULT 0.0",
    "ALTER TABLE crawl_sessions ADD COLUMN ad_total_area_px INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN ad_iab_standard_count INTEGER DEFAULT 0",
    # -- crawl_sessions: ad capture columns --
    "ALTER TABLE crawl_sessions ADD COLUMN ad_captures_total INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN ad_captures_failed INTEGER DEFAULT 0",
    # -- crawl_sessions: resource weight columns --
    "ALTER TABLE crawl_sessions ADD COLUMN rw_total_bytes INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN rw_content_1p_bytes INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN rw_cdn_bytes INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN rw_tracker_bytes INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN rw_ad_bytes INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN rw_functional_3p_bytes INTEGER DEFAULT 0",
    "ALTER TABLE crawl_sessions ADD COLUMN rw_unknown_3p_bytes INTEGER DEFAULT 0",
    # -- requests: new columns --
    "ALTER TABLE requests ADD COLUMN resource_category TEXT",
    "ALTER TABLE requests ADD COLUMN content_type TEXT",
    # -- new tables --
    """CREATE TABLE IF NOT EXISTS fingerprint_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES crawl_sessions(id),
        api TEXT NOT NULL,
        method TEXT NOT NULL,
        call_stack_domain TEXT,
        tracker_entity TEXT,
        details TEXT,
        timestamp TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS ad_elements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES crawl_sessions(id),
        selector TEXT,
        tag_name TEXT,
        ad_id TEXT,
        ad_class TEXT,
        x REAL,
        y REAL,
        width REAL,
        height REAL,
        is_visible BOOLEAN,
        is_iframe BOOLEAN,
        iframe_src TEXT,
        iab_size TEXT,
        ad_network TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS ad_captures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES crawl_sessions(id),
        ad_element_id INTEGER REFERENCES ad_elements(id),
        ad_index INTEGER,
        screenshot_path TEXT,
        metadata_path TEXT,
        width INTEGER,
        height INTEGER,
        capture_method TEXT
    )""",
    # -- new indexes --
    "CREATE INDEX IF NOT EXISTS idx_fp_events_session ON fingerprint_events(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_fp_events_api ON fingerprint_events(api)",
    "CREATE INDEX IF NOT EXISTS idx_ad_elements_session ON ad_elements(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_ad_captures_session ON ad_captures(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_requests_category ON requests(resource_category)",
]


def migrate(db_path: str) -> None:
    path = Path(db_path)
    if not path.exists():
        print(f"Database not found: {path}")
        sys.exit(1)

    conn = sqlite3.connect(str(path))
    applied = 0
    skipped = 0

    for stmt in MIGRATIONS:
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                skipped += 1
            elif "already exists" in str(e).lower():
                skipped += 1
            else:
                print(f"  ERROR: {e}")
                print(f"  Statement: {stmt[:80]}...")

    conn.commit()
    conn.close()

    print(f"Migration complete: {applied} applied, {skipped} already existed")
    print(f"Database: {path}")


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    migrate(db_path)
