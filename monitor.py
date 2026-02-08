#!/usr/bin/env python3
"""Real-time monitoring for Footprint Crawler progress."""

import sqlite3
import time
from datetime import datetime
from pathlib import Path

def get_progress_stats():
    """Get current crawl progress statistics."""
    db_path = Path("data/footprint.db")
    
    if not db_path.exists():
        return None
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Overall progress
    cursor.execute("""
        SELECT 
            COUNT(*) as total_sessions,
            COUNT(DISTINCT s.url) as unique_sites,
            COUNT(CASE WHEN cs.status = 'success' THEN 1 END) as successful,
            COUNT(CASE WHEN cs.status = 'error' THEN 1 END) as errors,
            COUNT(CASE WHEN cs.status = 'timeout' THEN 1 END) as timeouts,
            ROUND(AVG(CASE WHEN cs.status = 'success' THEN load_time_ms END)/1000, 1) as avg_load_time,
            ROUND(AVG(CASE WHEN cs.status = 'success' THEN total_requests END), 1) as avg_requests,
            ROUND(AVG(CASE WHEN cs.status = 'success' THEN third_party_requests END), 1) as avg_3p_requests,
            ROUND(AVG(CASE WHEN cs.status = 'success' THEN total_cookies_set END), 1) as avg_cookies,
            ROUND(AVG(CASE WHEN cs.status = 'success' THEN tracking_cookies_set END), 1) as avg_tracking_cookies
        FROM crawl_sessions cs
        JOIN sites s ON cs.site_id = s.id
    """)
    
    overall = cursor.fetchone()
    
    # By consent mode
    cursor.execute("""
        SELECT 
            consent_mode,
            COUNT(*) as sessions,
            COUNT(CASE WHEN status = 'success' THEN 1 END) as successful,
            ROUND(AVG(CASE WHEN status = 'success' THEN total_requests END), 1) as avg_requests,
            ROUND(AVG(CASE WHEN status = 'success' THEN tracking_cookies_set END), 1) as avg_tracking_cookies
        FROM crawl_sessions
        GROUP BY consent_mode
        ORDER BY consent_mode
    """)
    
    by_mode = cursor.fetchall()
    
    # Recent activity (last 10 completed)
    cursor.execute("""
        SELECT 
            s.url,
            cs.consent_mode,
            cs.total_requests,
            cs.third_party_requests,
            cs.total_cookies_set,
            cs.tracking_cookies_set,
            cs.load_time_ms/1000 as load_time_sec,
            cs.completed_at
        FROM crawl_sessions cs
        JOIN sites s ON cs.site_id = s.id
        WHERE cs.status = 'success' AND cs.completed_at IS NOT NULL
        ORDER BY cs.completed_at DESC
        LIMIT 10
    """)
    
    recent = cursor.fetchall()
    
    conn.close()
    
    return {
        'overall': overall,
        'by_mode': by_mode,
        'recent': recent,
        'timestamp': datetime.now().strftime('%H:%M:%S')
    }

def print_dashboard():
    """Print monitoring dashboard."""
    stats = get_progress_stats()
    
    if not stats:
        print("❌ Database not found or no data yet")
        return
    
    print("\n" + "="*80)
    print(f"🕷️  FOOTPRINT CRAWLER MONITOR - {stats['timestamp']}")
    print("="*80)
    
    overall = stats['overall']
    total_sessions, unique_sites, successful, errors, timeouts, avg_load, avg_req, avg_3p, avg_cookies, avg_tracking = overall
    
    # Progress bar
    progress_pct = (successful / 300) * 100 if successful else 0
    progress_bar = "█" * int(progress_pct/3) + "░" * (33 - int(progress_pct/3))
    
    print(f"\n📊 OVERALL PROGRESS: {successful}/300 sessions ({progress_pct:.1f}%)")
    print(f"   {progress_bar}")
    print(f"   🌐 Sites crawled: {unique_sites}/100")
    print(f"   ✅ Successful: {successful} | ❌ Errors: {errors} | ⏱️ Timeouts: {timeouts}")
    
    if avg_load:
        print(f"\n⚡ PERFORMANCE METRICS:")
        print(f"   📈 Avg load time: {avg_load}s")
        print(f"   🌐 Avg requests: {avg_req} total ({avg_3p} third-party)")
        print(f"   🍪 Avg cookies: {avg_cookies} total ({avg_tracking} tracking)")
    
    print(f"\n📋 BY CONSENT MODE:")
    for mode, sessions, success, req, tracking in stats['by_mode']:
        mode_icon = {"ignore": "🚫", "accept": "✅", "reject": "❌"}.get(mode, "❓")
        print(f"   {mode_icon} {mode:8} | {success:3}/{sessions:3} sessions | {req:6.1f} req | {tracking:4.1f} tracking cookies")
    
    if stats['recent']:
        print(f"\n🕐 RECENT ACTIVITY:")
        for url, mode, req, third_party, cookies, tracking, load_time, completed in stats['recent'][:5]:
            domain = url.replace('https://www.', '').replace('https://', '')
            print(f"   {domain:20} ({mode:6}) | {req:3}req ({third_party}3p) | {cookies}c ({tracking}t) | {load_time:.1f}s")

if __name__ == "__main__":
    try:
        while True:
            print_dashboard()
            time.sleep(30)  # Update every 30 seconds
    except KeyboardInterrupt:
        print("\n\n👋 Monitoring stopped")
