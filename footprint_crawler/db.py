"""SQLite database operations for the Footprint Crawler."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from .models import CookieRecord, CrawlResult, CrawlStatus, RequestRecord, SiteInfo

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    domain TEXT NOT NULL UNIQUE,
    category TEXT,
    rank_cz INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS crawl_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL REFERENCES sites(id),
    consent_mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    final_url TEXT,
    page_title TEXT,
    load_time_ms INTEGER,
    total_requests INTEGER DEFAULT 0,
    third_party_requests INTEGER DEFAULT 0,
    total_cookies_set INTEGER DEFAULT 0,
    tracking_cookies_set INTEGER DEFAULT 0,
    consent_banner_detected BOOLEAN,
    consent_cmp TEXT,
    consent_button_text TEXT,
    consent_action_taken BOOLEAN,
    screenshot_path TEXT,
    error TEXT,
    status TEXT NOT NULL,
    -- Phase 2: fingerprinting
    fp_severity TEXT,
    fp_event_count INTEGER DEFAULT 0,
    fp_canvas BOOLEAN DEFAULT 0,
    fp_webgl BOOLEAN DEFAULT 0,
    fp_audio BOOLEAN DEFAULT 0,
    fp_font BOOLEAN DEFAULT 0,
    fp_navigator BOOLEAN DEFAULT 0,
    fp_storage BOOLEAN DEFAULT 0,
    fp_unique_apis INTEGER DEFAULT 0,
    fp_unique_entities INTEGER DEFAULT 0,
    -- Phase 2: ad detection
    ad_count INTEGER DEFAULT 0,
    ad_visible_count INTEGER DEFAULT 0,
    ad_density REAL DEFAULT 0.0,
    ad_total_area_px INTEGER DEFAULT 0,
    ad_iab_standard_count INTEGER DEFAULT 0,
    -- Phase 2: ad capture
    ad_captures_total INTEGER DEFAULT 0,
    ad_captures_failed INTEGER DEFAULT 0,
    -- Phase 2: resource weight
    rw_total_bytes INTEGER DEFAULT 0,
    rw_content_1p_bytes INTEGER DEFAULT 0,
    rw_cdn_bytes INTEGER DEFAULT 0,
    rw_tracker_bytes INTEGER DEFAULT 0,
    rw_ad_bytes INTEGER DEFAULT 0,
    rw_functional_3p_bytes INTEGER DEFAULT 0,
    rw_unknown_3p_bytes INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES crawl_sessions(id),
    url TEXT NOT NULL,
    domain TEXT,
    method TEXT,
    resource_type TEXT,
    is_third_party BOOLEAN,
    tracker_entity TEXT,
    tracker_category TEXT,
    status_code INTEGER,
    response_size_bytes INTEGER,
    timing_ms REAL,
    timestamp TEXT,
    resource_category TEXT,
    content_type TEXT
);

CREATE TABLE IF NOT EXISTS cookies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES crawl_sessions(id),
    name TEXT,
    domain TEXT,
    value_hash TEXT,
    path TEXT,
    expires_at TEXT,
    lifetime_days REAL,
    is_secure BOOLEAN,
    is_http_only BOOLEAN,
    same_site TEXT,
    is_session BOOLEAN,
    is_tracking_cookie BOOLEAN,
    tracker_entity TEXT,
    set_before_consent BOOLEAN,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS fingerprint_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES crawl_sessions(id),
    api TEXT NOT NULL,
    method TEXT NOT NULL,
    call_stack_domain TEXT,
    tracker_entity TEXT,
    details TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS ad_elements (
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
);

CREATE TABLE IF NOT EXISTS ad_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES crawl_sessions(id),
    ad_element_id INTEGER REFERENCES ad_elements(id),
    ad_index INTEGER,
    screenshot_path TEXT,
    metadata_path TEXT,
    width INTEGER,
    height INTEGER,
    capture_method TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_site ON crawl_sessions(site_id);
CREATE INDEX IF NOT EXISTS idx_sessions_mode ON crawl_sessions(consent_mode);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON crawl_sessions(status);
CREATE INDEX IF NOT EXISTS idx_requests_session ON requests(session_id);
CREATE INDEX IF NOT EXISTS idx_requests_domain ON requests(domain);
CREATE INDEX IF NOT EXISTS idx_requests_tracker ON requests(tracker_entity);
CREATE INDEX IF NOT EXISTS idx_requests_category ON requests(resource_category);
CREATE INDEX IF NOT EXISTS idx_cookies_session ON cookies(session_id);
CREATE INDEX IF NOT EXISTS idx_cookies_domain ON cookies(domain);
CREATE INDEX IF NOT EXISTS idx_fp_events_session ON fingerprint_events(session_id);
CREATE INDEX IF NOT EXISTS idx_fp_events_api ON fingerprint_events(api);
CREATE INDEX IF NOT EXISTS idx_ad_elements_session ON ad_elements(session_id);
CREATE INDEX IF NOT EXISTS idx_ad_captures_session ON ad_captures(session_id);
"""


class Database:
    """Async SQLite database for crawl data storage."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database connection and create tables."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
        logger.info("Database connected: %s", self.db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def upsert_site(self, site: SiteInfo) -> int:
        """Insert a site or return its existing ID."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT id FROM sites WHERE domain = ?", (site.domain,)
        )
        row = await cursor.fetchone()
        if row:
            return row[0]

        cursor = await self._conn.execute(
            "INSERT INTO sites (url, domain, category, rank_cz) VALUES (?, ?, ?, ?)",
            (site.url, site.domain, site.category, site.rank_cz),
        )
        await self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def has_session(self, site_domain: str, consent_mode: str) -> bool:
        """Check if a successful crawl session already exists for this site+mode."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            """
            SELECT 1 FROM crawl_sessions cs
            JOIN sites s ON cs.site_id = s.id
            WHERE s.domain = ? AND cs.consent_mode = ? AND cs.status = ?
            LIMIT 1
            """,
            (site_domain, consent_mode, CrawlStatus.SUCCESS.value),
        )
        return await cursor.fetchone() is not None

    async def save_crawl_result(self, result: CrawlResult) -> int:
        """Save a complete crawl result (session + requests + cookies + Phase 2 data)."""
        assert self._conn is not None

        site_id = await self.upsert_site(result.site)

        third_party_requests = sum(1 for r in result.requests if r.is_third_party)
        tracking_cookies = sum(1 for c in result.cookies if c.is_tracking_cookie)

        consent = result.consent_info
        banner_detected = consent.banner_detected if consent else None
        cmp = consent.cmp_platform if consent else None
        button_text = consent.button_text if consent else None
        action_taken = consent.action_taken if consent else None

        # Phase 2: fingerprinting summary
        fp = result.fingerprint_result
        fp_severity = fp.severity.value if fp else None
        fp_event_count = len(fp.events) if fp else 0
        fp_canvas = fp.canvas_detected if fp else False
        fp_webgl = fp.webgl_detected if fp else False
        fp_audio = fp.audio_detected if fp else False
        fp_font = fp.font_detected if fp else False
        fp_navigator = fp.navigator_detected if fp else False
        fp_storage = fp.storage_detected if fp else False
        fp_unique_apis = fp.unique_apis if fp else 0
        fp_unique_entities = fp.unique_entities if fp else 0

        # Phase 2: ad detection summary
        ad = result.ad_detection_result
        ad_count = ad.total_ad_count if ad else 0
        ad_visible_count = ad.visible_ad_count if ad else 0
        ad_density = ad.ad_density if ad else 0.0
        ad_total_area_px = ad.total_ad_area_px if ad else 0
        ad_iab_standard_count = ad.iab_standard_count if ad else 0

        # Phase 2: ad capture summary
        ac = result.ad_capture_result
        ad_captures_total = ac.total_captured if ac else 0
        ad_captures_failed = ac.total_failed if ac else 0

        # Phase 2: resource weight summary
        rw = result.resource_weight
        rw_total_bytes = rw.total_bytes if rw else 0
        rw_content_1p_bytes = rw.content_1p_bytes if rw else 0
        rw_cdn_bytes = rw.cdn_bytes if rw else 0
        rw_tracker_bytes = rw.tracker_bytes if rw else 0
        rw_ad_bytes = rw.ad_bytes if rw else 0
        rw_functional_3p_bytes = rw.functional_3p_bytes if rw else 0
        rw_unknown_3p_bytes = rw.unknown_3p_bytes if rw else 0

        async with self._conn.cursor() as cur:
            # Insert session
            await cur.execute(
                """
                INSERT INTO crawl_sessions (
                    site_id, consent_mode, started_at, completed_at,
                    final_url, page_title, load_time_ms,
                    total_requests, third_party_requests,
                    total_cookies_set, tracking_cookies_set,
                    consent_banner_detected, consent_cmp,
                    consent_button_text, consent_action_taken,
                    screenshot_path, error, status,
                    fp_severity, fp_event_count, fp_canvas, fp_webgl,
                    fp_audio, fp_font, fp_navigator, fp_storage,
                    fp_unique_apis, fp_unique_entities,
                    ad_count, ad_visible_count, ad_density,
                    ad_total_area_px, ad_iab_standard_count,
                    ad_captures_total, ad_captures_failed,
                    rw_total_bytes, rw_content_1p_bytes, rw_cdn_bytes,
                    rw_tracker_bytes, rw_ad_bytes,
                    rw_functional_3p_bytes, rw_unknown_3p_bytes
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    site_id,
                    result.consent_mode.value,
                    result.started_at,
                    result.completed_at,
                    result.final_url,
                    result.page_title,
                    result.load_time_ms,
                    len(result.requests),
                    third_party_requests,
                    len(result.cookies),
                    tracking_cookies,
                    banner_detected,
                    cmp,
                    button_text,
                    action_taken,
                    result.screenshot_path,
                    result.error,
                    result.status.value,
                    fp_severity, fp_event_count, fp_canvas, fp_webgl,
                    fp_audio, fp_font, fp_navigator, fp_storage,
                    fp_unique_apis, fp_unique_entities,
                    ad_count, ad_visible_count, ad_density,
                    ad_total_area_px, ad_iab_standard_count,
                    ad_captures_total, ad_captures_failed,
                    rw_total_bytes, rw_content_1p_bytes, rw_cdn_bytes,
                    rw_tracker_bytes, rw_ad_bytes,
                    rw_functional_3p_bytes, rw_unknown_3p_bytes,
                ),
            )
            session_id = cur.lastrowid

            # Batch insert requests
            if result.requests:
                await cur.executemany(
                    """
                    INSERT INTO requests (
                        session_id, url, domain, method, resource_type,
                        is_third_party, tracker_entity, tracker_category,
                        status_code, response_size_bytes, timing_ms, timestamp,
                        resource_category, content_type
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            session_id,
                            r.url,
                            r.domain,
                            r.method,
                            r.resource_type,
                            r.is_third_party,
                            r.tracker_entity,
                            r.tracker_category,
                            r.status_code,
                            r.response_size_bytes,
                            r.timing_ms,
                            r.timestamp,
                            r.resource_category,
                            r.content_type,
                        )
                        for r in result.requests
                    ],
                )

            # Batch insert cookies
            if result.cookies:
                await cur.executemany(
                    """
                    INSERT INTO cookies (
                        session_id, name, domain, value_hash, path,
                        expires_at, lifetime_days, is_secure, is_http_only,
                        same_site, is_session, is_tracking_cookie,
                        tracker_entity, set_before_consent, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            session_id,
                            c.name,
                            c.domain,
                            c.value_hash,
                            c.path,
                            c.expires_at,
                            c.lifetime_days,
                            c.is_secure,
                            c.is_http_only,
                            c.same_site,
                            c.is_session,
                            c.is_tracking_cookie,
                            c.tracker_entity,
                            c.set_before_consent,
                            c.timestamp,
                        )
                        for c in result.cookies
                    ],
                )

            # Batch insert fingerprint events
            if fp and fp.events:
                await cur.executemany(
                    """
                    INSERT INTO fingerprint_events (
                        session_id, api, method, call_stack_domain,
                        tracker_entity, details, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            session_id,
                            e.api,
                            e.method,
                            e.call_stack_domain,
                            e.tracker_entity,
                            e.details,
                            e.timestamp,
                        )
                        for e in fp.events
                    ],
                )

            # Batch insert ad elements and captures
            if ad and ad.ads:
                for i, a in enumerate(ad.ads):
                    await cur.execute(
                        """
                        INSERT INTO ad_elements (
                            session_id, selector, tag_name, ad_id, ad_class,
                            x, y, width, height, is_visible, is_iframe,
                            iframe_src, iab_size, ad_network
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            a.selector,
                            a.tag_name,
                            a.ad_id,
                            a.ad_class,
                            a.x, a.y, a.width, a.height,
                            a.is_visible,
                            a.is_iframe,
                            a.iframe_src,
                            a.iab_size,
                            a.ad_network,
                        ),
                    )
                    ad_element_id = cur.lastrowid

                    # Match capture to this ad element by index
                    if ac and i < len(ac.captures):
                        cap = ac.captures[i]
                        await cur.execute(
                            """
                            INSERT INTO ad_captures (
                                session_id, ad_element_id, ad_index,
                                screenshot_path, metadata_path,
                                width, height, capture_method
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                session_id,
                                ad_element_id,
                                cap.ad_index,
                                cap.screenshot_path,
                                cap.metadata_path,
                                cap.width,
                                cap.height,
                                cap.capture_method,
                            ),
                        )

        await self._conn.commit()
        logger.debug(
            "Saved session %d: %s (%s) — %d requests, %d cookies",
            session_id, result.site.domain, result.consent_mode.value,
            len(result.requests), len(result.cookies),
        )
        return session_id  # type: ignore[return-value]

    async def get_stats(self) -> dict:
        """Get basic crawl statistics."""
        assert self._conn is not None
        stats = {}

        cursor = await self._conn.execute("SELECT COUNT(*) FROM sites")
        stats["total_sites"] = (await cursor.fetchone())[0]

        cursor = await self._conn.execute("SELECT COUNT(*) FROM crawl_sessions")
        stats["total_sessions"] = (await cursor.fetchone())[0]

        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM crawl_sessions WHERE status = ?",
            (CrawlStatus.SUCCESS.value,),
        )
        stats["successful_sessions"] = (await cursor.fetchone())[0]

        cursor = await self._conn.execute("SELECT COUNT(*) FROM requests")
        stats["total_requests"] = (await cursor.fetchone())[0]

        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM requests WHERE is_third_party = 1"
        )
        stats["third_party_requests"] = (await cursor.fetchone())[0]

        cursor = await self._conn.execute("SELECT COUNT(*) FROM cookies")
        stats["total_cookies"] = (await cursor.fetchone())[0]

        return stats
