#!/usr/bin/env python3
"""
Generate research CSVs from footprint.db database.
Exports comprehensive data for deep analysis of tracking, cookies, and consent behavior.
"""

import sqlite3
import csv
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / "footprint.db"
OUTPUT_DIR = Path(__file__).parent / "research_exports"


def ensure_output_dir():
    """Create output directory if it doesn't exist."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"📁 Output directory: {OUTPUT_DIR}")


def export_query(conn, filename, query, description):
    """Execute query and export results to CSV."""
    cursor = conn.execute(query)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    
    filepath = OUTPUT_DIR / filename
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    
    print(f"✅ {filename}: {len(rows)} rows - {description}")
    return len(rows)


def main():
    print("=" * 60)
    print("🔬 Footprint Research CSV Generator")
    print("=" * 60)
    
    ensure_output_dir()
    conn = sqlite3.connect(DB_PATH)
    
    # 1. Site Sessions Overview - Core crawl data per site/consent mode
    export_query(conn, "01_site_sessions_overview.csv", """
        SELECT 
            s.domain,
            s.category,
            s.rank_cz,
            cs.consent_mode,
            cs.status,
            cs.load_time_ms,
            cs.total_requests,
            cs.third_party_requests,
            cs.total_cookies_set,
            cs.tracking_cookies_set,
            cs.consent_banner_detected,
            cs.consent_cmp,
            cs.consent_button_text,
            cs.consent_action_taken,
            ROUND(CAST(cs.third_party_requests AS FLOAT) / NULLIF(cs.total_requests, 0) * 100, 1) as third_party_pct,
            cs.started_at,
            cs.completed_at
        FROM sites s
        JOIN crawl_sessions cs ON s.id = cs.site_id
        WHERE cs.status = 'success'
        ORDER BY s.rank_cz, s.domain, cs.consent_mode
    """, "Complete session data per site and consent mode")

    # 2. Consent Comparison - Side-by-side accept/ignore/reject comparison
    export_query(conn, "02_consent_comparison_pivot.csv", """
        SELECT 
            s.domain,
            s.category,
            s.rank_cz,
            MAX(CASE WHEN cs.consent_mode = 'accept' THEN cs.tracking_cookies_set END) as accept_tracking_cookies,
            MAX(CASE WHEN cs.consent_mode = 'ignore' THEN cs.tracking_cookies_set END) as ignore_tracking_cookies,
            MAX(CASE WHEN cs.consent_mode = 'reject' THEN cs.tracking_cookies_set END) as reject_tracking_cookies,
            MAX(CASE WHEN cs.consent_mode = 'accept' THEN cs.third_party_requests END) as accept_3p_requests,
            MAX(CASE WHEN cs.consent_mode = 'ignore' THEN cs.third_party_requests END) as ignore_3p_requests,
            MAX(CASE WHEN cs.consent_mode = 'reject' THEN cs.third_party_requests END) as reject_3p_requests,
            MAX(CASE WHEN cs.consent_mode = 'accept' THEN cs.total_cookies_set END) as accept_total_cookies,
            MAX(CASE WHEN cs.consent_mode = 'ignore' THEN cs.total_cookies_set END) as ignore_total_cookies,
            MAX(CASE WHEN cs.consent_mode = 'reject' THEN cs.total_cookies_set END) as reject_total_cookies
        FROM sites s
        JOIN crawl_sessions cs ON s.id = cs.site_id
        WHERE cs.status = 'success'
        GROUP BY s.domain, s.category, s.rank_cz
        ORDER BY s.rank_cz
    """, "Pivot table comparing consent modes side-by-side")

    # 3. Tracker Entities by Consent Mode
    export_query(conn, "03_tracker_entities_by_consent.csv", """
        SELECT 
            r.tracker_entity,
            r.tracker_category,
            cs.consent_mode,
            COUNT(DISTINCT s.domain) as sites_present,
            COUNT(*) as total_requests,
            ROUND(AVG(r.response_size_bytes), 0) as avg_response_bytes,
            ROUND(AVG(r.timing_ms), 1) as avg_timing_ms
        FROM requests r
        JOIN crawl_sessions cs ON r.session_id = cs.id
        JOIN sites s ON cs.site_id = s.id
        WHERE r.tracker_entity IS NOT NULL AND cs.status = 'success'
        GROUP BY r.tracker_entity, r.tracker_category, cs.consent_mode
        ORDER BY sites_present DESC, total_requests DESC
    """, "Tracker entities with reach and request volume per consent mode")

    # 4. Top Trackers Pivot - Compare tracker presence across consent modes
    export_query(conn, "04_top_trackers_pivot.csv", """
        WITH tracker_stats AS (
            SELECT 
                r.tracker_entity,
                r.tracker_category,
                cs.consent_mode,
                COUNT(DISTINCT s.domain) as sites_present,
                COUNT(*) as requests
            FROM requests r
            JOIN crawl_sessions cs ON r.session_id = cs.id
            JOIN sites s ON cs.site_id = s.id
            WHERE r.tracker_entity IS NOT NULL AND cs.status = 'success'
            GROUP BY r.tracker_entity, r.tracker_category, cs.consent_mode
        )
        SELECT 
            tracker_entity,
            tracker_category,
            MAX(CASE WHEN consent_mode = 'accept' THEN sites_present END) as accept_sites,
            MAX(CASE WHEN consent_mode = 'ignore' THEN sites_present END) as ignore_sites,
            MAX(CASE WHEN consent_mode = 'reject' THEN sites_present END) as reject_sites,
            MAX(CASE WHEN consent_mode = 'accept' THEN requests END) as accept_requests,
            MAX(CASE WHEN consent_mode = 'ignore' THEN requests END) as ignore_requests,
            MAX(CASE WHEN consent_mode = 'reject' THEN requests END) as reject_requests
        FROM tracker_stats
        GROUP BY tracker_entity, tracker_category
        ORDER BY (COALESCE(MAX(CASE WHEN consent_mode = 'accept' THEN sites_present END), 0) +
                  COALESCE(MAX(CASE WHEN consent_mode = 'ignore' THEN sites_present END), 0) +
                  COALESCE(MAX(CASE WHEN consent_mode = 'reject' THEN sites_present END), 0)) DESC
    """, "Tracker presence comparison across consent modes")

    # 5. Cookie Analysis - Detailed cookie behavior
    export_query(conn, "05_cookie_analysis.csv", """
        SELECT 
            c.name as cookie_name,
            c.domain as cookie_domain,
            c.tracker_entity,
            cs.consent_mode,
            COUNT(*) as occurrences,
            COUNT(DISTINCT s.domain) as sites_present,
            ROUND(AVG(c.lifetime_days), 1) as avg_lifetime_days,
            MAX(c.lifetime_days) as max_lifetime_days,
            SUM(CASE WHEN c.is_tracking_cookie THEN 1 ELSE 0 END) as tracking_count,
            SUM(CASE WHEN c.set_before_consent THEN 1 ELSE 0 END) as set_before_consent,
            SUM(CASE WHEN c.is_secure THEN 1 ELSE 0 END) as secure_count,
            SUM(CASE WHEN c.is_http_only THEN 1 ELSE 0 END) as http_only_count,
            c.same_site
        FROM cookies c
        JOIN crawl_sessions cs ON c.session_id = cs.id
        JOIN sites s ON cs.site_id = s.id
        WHERE cs.status = 'success'
        GROUP BY c.name, c.domain, cs.consent_mode, c.same_site
        ORDER BY sites_present DESC, occurrences DESC
    """, "Cookie attributes and behavior across consent modes")

    # 6. Pre-Consent Violations - Cookies set before consent
    export_query(conn, "06_preconsent_violations.csv", """
        SELECT 
            s.domain as site_domain,
            s.category,
            c.name as cookie_name,
            c.domain as cookie_domain,
            c.tracker_entity,
            c.lifetime_days,
            c.is_tracking_cookie,
            cs.consent_mode,
            cs.consent_cmp
        FROM cookies c
        JOIN crawl_sessions cs ON c.session_id = cs.id
        JOIN sites s ON cs.site_id = s.id
        WHERE c.set_before_consent = 1 AND cs.status = 'success'
        ORDER BY s.domain, cs.consent_mode
    """, "Cookies set before user consent action")

    # 7. Third-Party Domains - All third-party request domains
    export_query(conn, "07_third_party_domains.csv", """
        SELECT 
            r.domain as third_party_domain,
            r.tracker_entity,
            r.tracker_category,
            cs.consent_mode,
            COUNT(*) as requests,
            COUNT(DISTINCT s.domain) as sites_present,
            GROUP_CONCAT(DISTINCT r.resource_type) as resource_types
        FROM requests r
        JOIN crawl_sessions cs ON r.session_id = cs.id
        JOIN sites s ON cs.site_id = s.id
        WHERE r.is_third_party = 1 AND cs.status = 'success'
        GROUP BY r.domain, r.tracker_entity, r.tracker_category, cs.consent_mode
        ORDER BY sites_present DESC, requests DESC
    """, "Third-party domains with tracking classification")

    # 8. Category Summary - Tracking by site category
    export_query(conn, "08_category_summary.csv", """
        SELECT 
            s.category,
            cs.consent_mode,
            COUNT(DISTINCT s.domain) as sites,
            ROUND(AVG(cs.total_requests), 1) as avg_requests,
            ROUND(AVG(cs.third_party_requests), 1) as avg_3p_requests,
            ROUND(AVG(cs.total_cookies_set), 1) as avg_cookies,
            ROUND(AVG(cs.tracking_cookies_set), 1) as avg_tracking_cookies,
            SUM(cs.consent_banner_detected) as sites_with_banner,
            ROUND(AVG(cs.load_time_ms), 0) as avg_load_time_ms
        FROM sites s
        JOIN crawl_sessions cs ON s.id = cs.site_id
        WHERE cs.status = 'success'
        GROUP BY s.category, cs.consent_mode
        ORDER BY s.category, cs.consent_mode
    """, "Aggregated tracking metrics by site category")

    # 9. CMP (Consent Management Platform) Analysis
    export_query(conn, "09_cmp_analysis.csv", """
        SELECT 
            cs.consent_cmp,
            cs.consent_mode,
            COUNT(*) as sessions,
            COUNT(DISTINCT s.domain) as sites,
            ROUND(AVG(cs.tracking_cookies_set), 1) as avg_tracking_cookies,
            ROUND(AVG(cs.third_party_requests), 1) as avg_3p_requests,
            SUM(cs.consent_action_taken) as consent_actions_taken
        FROM crawl_sessions cs
        JOIN sites s ON cs.site_id = s.id
        WHERE cs.status = 'success' AND cs.consent_cmp IS NOT NULL
        GROUP BY cs.consent_cmp, cs.consent_mode
        ORDER BY sites DESC
    """, "Consent Management Platform effectiveness")

    # 10. Resource Types - What types of resources are third-party
    export_query(conn, "10_resource_types.csv", """
        SELECT 
            r.resource_type,
            r.is_third_party,
            cs.consent_mode,
            COUNT(*) as requests,
            ROUND(AVG(r.response_size_bytes), 0) as avg_size_bytes,
            ROUND(SUM(r.response_size_bytes) / 1024.0 / 1024.0, 2) as total_size_mb
        FROM requests r
        JOIN crawl_sessions cs ON r.session_id = cs.id
        WHERE cs.status = 'success'
        GROUP BY r.resource_type, r.is_third_party, cs.consent_mode
        ORDER BY requests DESC
    """, "Resource type breakdown with sizes")

    # 11. Long-Lived Tracking Cookies
    export_query(conn, "11_long_lived_cookies.csv", """
        SELECT 
            c.name,
            c.domain,
            c.tracker_entity,
            c.lifetime_days,
            c.is_tracking_cookie,
            COUNT(DISTINCT s.domain) as sites_present,
            GROUP_CONCAT(DISTINCT cs.consent_mode) as consent_modes
        FROM cookies c
        JOIN crawl_sessions cs ON c.session_id = cs.id
        JOIN sites s ON cs.site_id = s.id
        WHERE c.lifetime_days > 365 AND cs.status = 'success'
        GROUP BY c.name, c.domain, c.tracker_entity, c.lifetime_days, c.is_tracking_cookie
        ORDER BY c.lifetime_days DESC
    """, "Cookies with lifetime over 1 year")

    # 12. Sites Raw Data - Complete site list with basic stats
    export_query(conn, "12_sites_raw.csv", """
        SELECT 
            s.id,
            s.url,
            s.domain,
            s.category,
            s.rank_cz,
            s.created_at,
            (SELECT COUNT(*) FROM crawl_sessions WHERE site_id = s.id AND status = 'success') as successful_crawls,
            (SELECT COUNT(*) FROM crawl_sessions WHERE site_id = s.id AND status = 'error') as failed_crawls
        FROM sites s
        ORDER BY s.rank_cz
    """, "Complete site list with crawl statistics")

    conn.close()
    
    print("=" * 60)
    print(f"✨ All CSVs exported to: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
