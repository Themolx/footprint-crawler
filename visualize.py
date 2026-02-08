#!/usr/bin/env python3
"""Footprint Crawler — Visualization & Analysis Tool.

Generates charts, reports, and data exports from the crawl database.

Usage:
    python visualize.py                    # Generate all charts
    python visualize.py --report           # Print text report to terminal
    python visualize.py --export-csv       # Export data as CSV files
    python visualize.py --output-dir viz/  # Custom output directory
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker


DB_PATH = "data/footprint.db"
OUTPUT_DIR = "output/viz"


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ─── Chart 1: Consent comparison bar chart ───────────────────────────

def chart_consent_comparison(conn: sqlite3.Connection, out: Path) -> None:
    """Compare tracking metrics across ignore/accept/reject modes."""
    rows = conn.execute("""
        SELECT consent_mode,
               ROUND(AVG(third_party_requests), 1) as avg_3p,
               ROUND(AVG(tracking_cookies_set), 1) as avg_trk,
               ROUND(AVG(total_cookies_set), 1) as avg_cook,
               ROUND(AVG(total_requests), 1) as avg_req
        FROM crawl_sessions WHERE status='success'
        GROUP BY consent_mode
        ORDER BY consent_mode
    """).fetchall()

    modes = [r["consent_mode"] for r in rows]
    avg_3p = [r["avg_3p"] for r in rows]
    avg_trk = [r["avg_trk"] for r in rows]
    avg_cook = [r["avg_cook"] for r in rows]

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    colors = {"accept": "#e74c3c", "ignore": "#95a5a6", "reject": "#2ecc71"}
    bar_colors = [colors.get(m, "#333") for m in modes]

    axes[0].bar(modes, avg_3p, color=bar_colors, edgecolor="white", linewidth=0.5)
    axes[0].set_title("Avg 3rd-Party Requests", fontweight="bold")
    axes[0].set_ylabel("Requests per site")
    for i, v in enumerate(avg_3p):
        axes[0].text(i, v + 1, str(v), ha="center", fontsize=11)

    axes[1].bar(modes, avg_trk, color=bar_colors, edgecolor="white", linewidth=0.5)
    axes[1].set_title("Avg Tracking Cookies", fontweight="bold")
    axes[1].set_ylabel("Cookies per site")
    for i, v in enumerate(avg_trk):
        axes[1].text(i, v + 0.1, str(v), ha="center", fontsize=11)

    axes[2].bar(modes, avg_cook, color=bar_colors, edgecolor="white", linewidth=0.5)
    axes[2].set_title("Avg Total Cookies", fontweight="bold")
    axes[2].set_ylabel("Cookies per site")
    for i, v in enumerate(avg_cook):
        axes[2].text(i, v + 0.1, str(v), ha="center", fontsize=11)

    fig.suptitle("Does Cookie Consent Actually Work?", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    fig.savefig(out / "consent_comparison.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'consent_comparison.png'}")


# ─── Chart 2: Top tracker entities ────────────────────────────────────

def chart_top_trackers(conn: sqlite3.Connection, out: Path) -> None:
    """Horizontal bar chart of top tracker entities by site reach."""
    rows = conn.execute("""
        SELECT tracker_entity,
               COUNT(DISTINCT cs.site_id) as sites,
               COUNT(*) as reqs
        FROM requests r
        JOIN crawl_sessions cs ON r.session_id = cs.id
        WHERE r.tracker_entity IS NOT NULL AND cs.consent_mode='ignore' AND cs.status='success'
        GROUP BY tracker_entity ORDER BY sites DESC LIMIT 20
    """).fetchall()

    entities = [r["tracker_entity"] for r in rows][::-1]
    sites = [r["sites"] for r in rows][::-1]

    fig, ax = plt.subplots(figsize=(10, 8))
    colors_map = {
        "Google": "#4285F4", "Meta": "#1877F2", "Seznam.cz": "#cc0000",
        "Microsoft": "#00a4ef", "Amazon": "#FF9900", "Criteo": "#f5811f",
        "Adform": "#6c5ce7", "Gemius": "#00b894", "R2B2": "#d63031",
    }
    bar_colors = [colors_map.get(e, "#636e72") for e in entities]

    bars = ax.barh(entities, sites, color=bar_colors, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Number of Czech sites with this tracker")
    ax.set_title("Who Is Watching the Czech Internet?", fontsize=14, fontweight="bold")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    for bar, val in zip(bars, sites):
        ax.text(val + 0.5, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", fontsize=10)

    plt.tight_layout()
    fig.savefig(out / "top_trackers.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'top_trackers.png'}")


# ─── Chart 3: Tracking by category ────────────────────────────────────

def chart_tracking_by_category(conn: sqlite3.Connection, out: Path) -> None:
    """Bar chart of average 3rd-party requests by site category."""
    rows = conn.execute("""
        SELECT s.category,
               COUNT(DISTINCT s.id) as sites,
               ROUND(AVG(cs.third_party_requests), 1) as avg_3p,
               ROUND(AVG(cs.tracking_cookies_set), 1) as avg_trk
        FROM crawl_sessions cs JOIN sites s ON cs.site_id = s.id
        WHERE cs.consent_mode='ignore' AND cs.status='success'
        GROUP BY s.category ORDER BY AVG(cs.third_party_requests) DESC
    """).fetchall()

    cats = [f"{r['category']}\n({r['sites']} sites)" for r in rows]
    avg_3p = [r["avg_3p"] for r in rows]
    avg_trk = [r["avg_trk"] for r in rows]

    fig, ax = plt.subplots(figsize=(12, 6))
    x = range(len(cats))
    width = 0.4

    bars1 = ax.bar([i - width/2 for i in x], avg_3p, width, label="Avg 3rd-party requests",
                   color="#e74c3c", alpha=0.85)
    bars2 = ax.bar([i + width/2 for i in x], avg_trk, width, label="Avg tracking cookies",
                   color="#2c3e50", alpha=0.85)

    ax.set_xticks(list(x))
    ax.set_xticklabels(cats, fontsize=9)
    ax.set_ylabel("Count per site")
    ax.set_title("Tracking Intensity by Website Category", fontsize=14, fontweight="bold")
    ax.legend()

    plt.tight_layout()
    fig.savefig(out / "tracking_by_category.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'tracking_by_category.png'}")


# ─── Chart 4: Pre-consent vs post-consent cookies ────────────────────

def chart_pre_post_consent(conn: sqlite3.Connection, out: Path) -> None:
    """Compare cookies set before vs after consent action."""
    data = {}
    for mode in ["accept", "reject"]:
        rows = conn.execute("""
            SELECT
                CASE WHEN c.set_before_consent=1 THEN 'before' ELSE 'after' END as timing,
                COUNT(*) as total,
                SUM(CASE WHEN c.is_tracking_cookie=1 THEN 1 ELSE 0 END) as tracking
            FROM cookies c
            JOIN crawl_sessions cs ON c.session_id = cs.id
            WHERE cs.consent_mode=? AND cs.status='success'
            GROUP BY c.set_before_consent
        """, (mode,)).fetchall()
        data[mode] = {r["timing"]: {"total": r["total"], "tracking": r["tracking"]} for r in rows}

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    for idx, mode in enumerate(["accept", "reject"]):
        ax = axes[idx]
        before = data[mode].get("before", {"total": 0, "tracking": 0})
        after = data[mode].get("after", {"total": 0, "tracking": 0})

        categories = ["Before Consent", "After Consent"]
        tracking = [before["tracking"], after["tracking"]]
        functional = [before["total"] - before["tracking"], after["total"] - after["tracking"]]

        ax.bar(categories, functional, label="Functional", color="#2ecc71", alpha=0.85)
        ax.bar(categories, tracking, bottom=functional, label="Tracking", color="#e74c3c", alpha=0.85)
        ax.set_title(f"Cookies — {mode.upper()} mode", fontweight="bold")
        ax.set_ylabel("Number of cookies")
        ax.legend()

        for i, (f, t) in enumerate(zip(functional, tracking)):
            ax.text(i, f + t + 2, f"{f+t}", ha="center", fontsize=11, fontweight="bold")

    fig.suptitle("When Are Tracking Cookies Set?", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    fig.savefig(out / "pre_post_consent.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'pre_post_consent.png'}")


# ─── Chart 5: CMP platform distribution ──────────────────────────────

def chart_cmp_distribution(conn: sqlite3.Connection, out: Path) -> None:
    """Pie chart of consent management platforms detected."""
    rows = conn.execute("""
        SELECT consent_cmp, COUNT(*) as cnt
        FROM crawl_sessions
        WHERE consent_banner_detected=1 AND consent_cmp IS NOT NULL
        GROUP BY consent_cmp ORDER BY cnt DESC
    """).fetchall()

    if not rows:
        return

    labels = [r["consent_cmp"] for r in rows]
    sizes = [r["cnt"] for r in rows]

    fig, ax = plt.subplots(figsize=(8, 8))
    colors = plt.cm.Set3.colors[:len(labels)]
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct="%1.0f%%",
        colors=colors, startangle=90, pctdistance=0.85,
    )
    for text in autotexts:
        text.set_fontsize(10)
    ax.set_title("Consent Management Platforms Detected", fontsize=14, fontweight="bold")

    plt.tight_layout()
    fig.savefig(out / "cmp_distribution.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'cmp_distribution.png'}")


# ─── Chart 6: Top tracked sites ──────────────────────────────────────

def chart_top_tracked_sites(conn: sqlite3.Connection, out: Path) -> None:
    """Horizontal bar chart of most-tracked sites."""
    rows = conn.execute("""
        SELECT s.domain, s.category, cs.third_party_requests, cs.tracking_cookies_set
        FROM crawl_sessions cs JOIN sites s ON cs.site_id = s.id
        WHERE cs.consent_mode='ignore' AND cs.status='success'
        ORDER BY cs.third_party_requests DESC LIMIT 25
    """).fetchall()

    domains = [f"{r['domain']} [{r['category']}]" for r in rows][::-1]
    reqs = [r["third_party_requests"] for r in rows][::-1]

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.barh(domains, reqs, color="#e74c3c", alpha=0.85, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("3rd-party requests (ignore mode)")
    ax.set_title("Most Tracked Czech Websites", fontsize=14, fontweight="bold")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    plt.tight_layout()
    fig.savefig(out / "top_tracked_sites.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'top_tracked_sites.png'}")


# ─── Chart 7: Cookie lifetime distribution ────────────────────────────

def chart_cookie_lifetimes(conn: sqlite3.Connection, out: Path) -> None:
    """Histogram of cookie lifetimes in days."""
    rows = conn.execute("""
        SELECT lifetime_days FROM cookies
        WHERE lifetime_days IS NOT NULL AND lifetime_days > 0 AND lifetime_days < 3650
    """).fetchall()

    lifetimes = [r["lifetime_days"] for r in rows]
    if not lifetimes:
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(lifetimes, bins=50, color="#3498db", alpha=0.85, edgecolor="white")
    ax.axvline(x=365, color="#e74c3c", linestyle="--", linewidth=2, label="1 year")
    ax.axvline(x=180, color="#f39c12", linestyle="--", linewidth=1.5, label="6 months")
    ax.set_xlabel("Cookie lifetime (days)")
    ax.set_ylabel("Number of cookies")
    ax.set_title("Cookie Lifetime Distribution", fontsize=14, fontweight="bold")
    ax.legend()

    plt.tight_layout()
    fig.savefig(out / "cookie_lifetimes.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'cookie_lifetimes.png'}")


# ─── Network graph export (JSON for D3.js / Gephi) ───────────────────

def export_network_graph(conn: sqlite3.Connection, out: Path) -> None:
    """Export tracker network as JSON for D3.js force-directed graph."""
    # Nodes: sites + tracker entities
    sites = conn.execute("""
        SELECT DISTINCT s.domain, s.category
        FROM sites s
        JOIN crawl_sessions cs ON cs.site_id = s.id
        WHERE cs.status='success' AND cs.consent_mode='ignore'
    """).fetchall()

    trackers = conn.execute("""
        SELECT tracker_entity, tracker_category, COUNT(DISTINCT cs.site_id) as reach
        FROM requests r
        JOIN crawl_sessions cs ON r.session_id = cs.id
        WHERE r.tracker_entity IS NOT NULL AND cs.consent_mode='ignore' AND cs.status='success'
        GROUP BY tracker_entity
    """).fetchall()

    # Edges: site -> tracker
    edges = conn.execute("""
        SELECT DISTINCT s.domain, r.tracker_entity, COUNT(*) as weight
        FROM requests r
        JOIN crawl_sessions cs ON r.session_id = cs.id
        JOIN sites s ON cs.site_id = s.id
        WHERE r.tracker_entity IS NOT NULL AND cs.consent_mode='ignore' AND cs.status='success'
        GROUP BY s.domain, r.tracker_entity
    """).fetchall()

    nodes = []
    for s in sites:
        nodes.append({
            "id": s["domain"],
            "type": "site",
            "category": s["category"],
            "size": 3,
        })
    for t in trackers:
        nodes.append({
            "id": t["tracker_entity"],
            "type": "tracker",
            "category": t["tracker_category"],
            "size": max(5, t["reach"]),
        })

    links = []
    for e in edges:
        links.append({
            "source": e["domain"],
            "target": e["tracker_entity"],
            "weight": e["weight"],
        })

    graph = {"nodes": nodes, "links": links}
    graph_path = out / "network_graph.json"
    with open(graph_path, "w") as f:
        json.dump(graph, f, indent=2)
    print(f"  -> {graph_path} ({len(nodes)} nodes, {len(links)} edges)")


# ─── CSV Export ───────────────────────────────────────────────────────

def export_csv(conn: sqlite3.Connection, out: Path) -> None:
    """Export key tables as CSV for analysis in Excel/R/Pandas."""
    exports = {
        "sessions.csv": """
            SELECT s.domain, s.category, cs.consent_mode, cs.status,
                   cs.total_requests, cs.third_party_requests,
                   cs.total_cookies_set, cs.tracking_cookies_set,
                   cs.consent_banner_detected, cs.consent_cmp,
                   cs.consent_action_taken, cs.load_time_ms,
                   cs.started_at, cs.completed_at
            FROM crawl_sessions cs
            JOIN sites s ON cs.site_id = s.id
            ORDER BY s.domain, cs.consent_mode
        """,
        "tracker_reach.csv": """
            SELECT r.tracker_entity, r.tracker_category,
                   COUNT(DISTINCT cs.site_id) as sites_present,
                   COUNT(*) as total_requests,
                   cs.consent_mode
            FROM requests r
            JOIN crawl_sessions cs ON r.session_id = cs.id
            WHERE r.tracker_entity IS NOT NULL AND cs.status='success'
            GROUP BY r.tracker_entity, cs.consent_mode
            ORDER BY sites_present DESC
        """,
        "cookies_summary.csv": """
            SELECT c.name, c.domain, c.is_tracking_cookie, c.tracker_entity,
                   c.set_before_consent, c.is_session, c.lifetime_days,
                   c.same_site, cs.consent_mode, s.domain as site_domain
            FROM cookies c
            JOIN crawl_sessions cs ON c.session_id = cs.id
            JOIN sites s ON cs.site_id = s.id
            WHERE cs.status='success'
            ORDER BY c.domain, c.name
        """,
    }

    csv_dir = out / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    for filename, query in exports.items():
        rows = conn.execute(query).fetchall()
        if not rows:
            continue
        filepath = csv_dir / filename
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(rows[0].keys())
            writer.writerows(rows)
        print(f"  -> {filepath} ({len(rows)} rows)")


# ─── Text Report ──────────────────────────────────────────────────────

def print_report(conn: sqlite3.Connection) -> None:
    """Print a comprehensive text report."""
    print()
    print("=" * 70)
    print("  FOOTPRINT CRAWLER — ANALYSIS REPORT")
    print("=" * 70)

    # Overview
    total_sites = conn.execute("SELECT COUNT(DISTINCT site_id) FROM crawl_sessions WHERE status='success'").fetchone()[0]
    total_sessions = conn.execute("SELECT COUNT(*) FROM crawl_sessions WHERE status='success'").fetchone()[0]
    total_req = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    total_3p = conn.execute("SELECT COUNT(*) FROM requests WHERE is_third_party=1").fetchone()[0]

    print(f"\n  Sites crawled:    {total_sites}")
    print(f"  Total sessions:   {total_sessions}")
    print(f"  Total requests:   {total_req:,}")
    print(f"  3rd-party:        {total_3p:,} ({total_3p*100//max(total_req,1)}%)")

    # Consent comparison
    print(f"\n{'  CONSENT COMPARISON':─<70}")
    print(f"  {'Mode':<10} {'Avg 3P Req':>12} {'Avg Trk Cookie':>16} {'Avg Cookies':>12}")
    print(f"  {'─'*10} {'─'*12} {'─'*16} {'─'*12}")
    for row in conn.execute("""
        SELECT consent_mode, ROUND(AVG(third_party_requests),1),
               ROUND(AVG(tracking_cookies_set),1), ROUND(AVG(total_cookies_set),1)
        FROM crawl_sessions WHERE status='success' GROUP BY consent_mode
    """):
        print(f"  {row[0]:<10} {row[1]:>12} {row[2]:>16} {row[3]:>12}")

    accept_3p = conn.execute("SELECT AVG(third_party_requests) FROM crawl_sessions WHERE status='success' AND consent_mode='accept'").fetchone()[0]
    ignore_3p = conn.execute("SELECT AVG(third_party_requests) FROM crawl_sessions WHERE status='success' AND consent_mode='ignore'").fetchone()[0]
    reject_3p = conn.execute("SELECT AVG(third_party_requests) FROM crawl_sessions WHERE status='success' AND consent_mode='reject'").fetchone()[0]

    if ignore_3p and accept_3p:
        pct = (accept_3p - ignore_3p) / ignore_3p * 100
        print(f"\n  Accepting cookies increases 3rd-party requests by {pct:+.1f}%")
    if ignore_3p and reject_3p:
        pct = (reject_3p - ignore_3p) / ignore_3p * 100
        print(f"  Rejecting cookies changes 3rd-party requests by {pct:+.1f}%")

    # Top trackers
    print(f"\n{'  TOP 15 TRACKERS':─<70}")
    print(f"  {'Entity':<25} {'Sites':>6} {'Requests':>10}")
    print(f"  {'─'*25} {'─'*6} {'─'*10}")
    for row in conn.execute("""
        SELECT tracker_entity, COUNT(DISTINCT cs.site_id), COUNT(*)
        FROM requests r JOIN crawl_sessions cs ON r.session_id = cs.id
        WHERE r.tracker_entity IS NOT NULL AND cs.consent_mode='ignore' AND cs.status='success'
        GROUP BY tracker_entity ORDER BY COUNT(DISTINCT cs.site_id) DESC LIMIT 15
    """):
        print(f"  {row[0]:<25} {row[1]:>6} {row[2]:>10}")

    # Banner detection
    total_accept = conn.execute("SELECT COUNT(*) FROM crawl_sessions WHERE status='success' AND consent_mode='accept'").fetchone()[0]
    banners = conn.execute("SELECT COUNT(*) FROM crawl_sessions WHERE status='success' AND consent_mode='accept' AND consent_banner_detected=1").fetchone()[0]
    acted = conn.execute("SELECT COUNT(*) FROM crawl_sessions WHERE status='success' AND consent_mode='accept' AND consent_action_taken=1").fetchone()[0]

    print(f"\n{'  CONSENT BANNERS':─<70}")
    print(f"  Banners detected:  {banners}/{total_accept} ({banners*100//max(total_accept,1)}%)")
    print(f"  Banners clicked:   {acted}/{total_accept} ({acted*100//max(total_accept,1)}%)")

    print()
    print("=" * 70)


# ═══════════════════════════════════════════════════════════════════════
# Phase 2 Charts
# ═══════════════════════════════════════════════════════════════════════

# ─── Chart 8: Fingerprint severity distribution ──────────────────────

def chart_fingerprint_severity(conn: sqlite3.Connection, out: Path) -> None:
    """Bar chart: how many sites use none/passive/active/aggressive fingerprinting."""
    rows = conn.execute("""
        SELECT fp_severity, COUNT(*) as cnt
        FROM crawl_sessions
        WHERE status='success' AND consent_mode='ignore' AND fp_severity IS NOT NULL
        GROUP BY fp_severity
        ORDER BY CASE fp_severity
            WHEN 'none' THEN 0 WHEN 'passive' THEN 1
            WHEN 'active' THEN 2 WHEN 'aggressive' THEN 3 END
    """).fetchall()
    if not rows:
        return

    levels = [r["fp_severity"] for r in rows]
    counts = [r["cnt"] for r in rows]
    colors = {"none": "#2ecc71", "passive": "#f39c12", "active": "#e74c3c", "aggressive": "#8e44ad"}
    bar_colors = [colors.get(l, "#333") for l in levels]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(levels, counts, color=bar_colors, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Fingerprinting severity")
    ax.set_ylabel("Number of sites")
    ax.set_title("Browser Fingerprinting on Czech Websites", fontsize=14, fontweight="bold")
    for bar, val in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width()/2, val + 0.5, str(val), ha="center", fontsize=11)

    plt.tight_layout()
    fig.savefig(out / "fingerprint_severity.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'fingerprint_severity.png'}")


# ─── Chart 9: Fingerprint vectors by entity ──────────────────────────

def chart_fingerprint_vectors(conn: sqlite3.Connection, out: Path) -> None:
    """Bar chart: which fingerprinting techniques are used, attributed to tracker entities."""
    rows = conn.execute("""
        SELECT api, tracker_entity, COUNT(*) as cnt
        FROM fingerprint_events
        WHERE tracker_entity IS NOT NULL
        GROUP BY api, tracker_entity
        ORDER BY cnt DESC
    """).fetchall()
    if not rows:
        return

    # Aggregate by API
    api_counts = defaultdict(int)
    for r in rows:
        api_counts[r["api"]] += r["cnt"]

    apis = sorted(api_counts, key=api_counts.get, reverse=True)
    counts = [api_counts[a] for a in apis]

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = {"canvas": "#e74c3c", "webgl": "#3498db", "audio": "#9b59b6",
              "navigator": "#f39c12", "font": "#1abc9c", "storage": "#e67e22"}
    bar_colors = [colors.get(a, "#636e72") for a in apis]

    ax.bar(apis, counts, color=bar_colors, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Fingerprinting API")
    ax.set_ylabel("Total events detected")
    ax.set_title("Fingerprinting Techniques Used", fontsize=14, fontweight="bold")

    plt.tight_layout()
    fig.savefig(out / "fingerprint_vectors.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'fingerprint_vectors.png'}")


# ─── Chart 10: Fingerprinting vs consent mode ────────────────────────

def chart_fingerprint_vs_consent(conn: sqlite3.Connection, out: Path) -> None:
    """Grouped bar: does fingerprinting change across consent modes?"""
    rows = conn.execute("""
        SELECT consent_mode, fp_severity, COUNT(*) as cnt
        FROM crawl_sessions
        WHERE status='success' AND fp_severity IS NOT NULL
        GROUP BY consent_mode, fp_severity
    """).fetchall()
    if not rows:
        return

    modes = ["ignore", "accept", "reject"]
    severities = ["none", "passive", "active", "aggressive"]
    data = defaultdict(lambda: defaultdict(int))
    for r in rows:
        data[r["consent_mode"]][r["fp_severity"]] = r["cnt"]

    x = range(len(modes))
    width = 0.2
    sev_colors = {"none": "#2ecc71", "passive": "#f39c12", "active": "#e74c3c", "aggressive": "#8e44ad"}

    fig, ax = plt.subplots(figsize=(10, 5))
    for i, sev in enumerate(severities):
        vals = [data[m][sev] for m in modes]
        ax.bar([xi + i * width for xi in x], vals, width,
               label=sev, color=sev_colors.get(sev, "#333"))

    ax.set_xticks([xi + 1.5 * width for xi in x])
    ax.set_xticklabels(modes)
    ax.set_ylabel("Number of sites")
    ax.set_title("Fingerprinting Doesn't Care About Consent", fontsize=14, fontweight="bold")
    ax.legend()

    plt.tight_layout()
    fig.savefig(out / "fingerprint_vs_consent.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'fingerprint_vs_consent.png'}")


# ─── Chart 11: Ad density distribution ───────────────────────────────

def chart_ad_density_distribution(conn: sqlite3.Connection, out: Path) -> None:
    """Histogram of ad density percentages across all sites."""
    rows = conn.execute("""
        SELECT ad_density FROM crawl_sessions
        WHERE status='success' AND consent_mode='ignore' AND ad_density > 0
    """).fetchall()
    if not rows:
        return

    densities = [r["ad_density"] * 100 for r in rows]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(densities, bins=30, color="#e74c3c", alpha=0.85, edgecolor="white")
    ax.set_xlabel("Ad density (% of viewport)")
    ax.set_ylabel("Number of sites")
    ax.set_title("How Much of Czech Websites Is Advertising?", fontsize=14, fontweight="bold")
    avg = sum(densities) / len(densities) if densities else 0
    ax.axvline(x=avg, color="#2c3e50", linestyle="--", linewidth=2, label=f"Average: {avg:.1f}%")
    ax.legend()

    plt.tight_layout()
    fig.savefig(out / "ad_density_distribution.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'ad_density_distribution.png'}")


# ─── Chart 12: Ad network reach ──────────────────────────────────────

def chart_ad_network_reach(conn: sqlite3.Connection, out: Path) -> None:
    """Horizontal bar: which ad networks appear on the most sites."""
    rows = conn.execute("""
        SELECT ad_network, COUNT(DISTINCT cs.site_id) as sites, COUNT(*) as elements
        FROM ad_elements ae
        JOIN crawl_sessions cs ON ae.session_id = cs.id
        WHERE ae.ad_network IS NOT NULL AND cs.consent_mode='ignore' AND cs.status='success'
        GROUP BY ad_network ORDER BY sites DESC LIMIT 15
    """).fetchall()
    if not rows:
        return

    networks = [r["ad_network"] for r in rows][::-1]
    sites = [r["sites"] for r in rows][::-1]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(networks, sites, color="#e74c3c", alpha=0.85, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Number of sites")
    ax.set_title("Ad Networks on Czech Websites", fontsize=14, fontweight="bold")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    plt.tight_layout()
    fig.savefig(out / "ad_network_reach.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'ad_network_reach.png'}")


# ─── Chart 13: Ad density by category ────────────────────────────────

def chart_ad_density_by_category(conn: sqlite3.Connection, out: Path) -> None:
    """Bar chart: average ad density by site category."""
    rows = conn.execute("""
        SELECT s.category, ROUND(AVG(cs.ad_density) * 100, 1) as avg_density,
               COUNT(DISTINCT s.id) as sites
        FROM crawl_sessions cs JOIN sites s ON cs.site_id = s.id
        WHERE cs.consent_mode='ignore' AND cs.status='success' AND cs.ad_density > 0
        GROUP BY s.category ORDER BY AVG(cs.ad_density) DESC
    """).fetchall()
    if not rows:
        return

    cats = [f"{r['category']}\n({r['sites']} sites)" for r in rows]
    densities = [r["avg_density"] for r in rows]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(cats, densities, color="#e67e22", alpha=0.85, edgecolor="white", linewidth=0.5)
    ax.set_ylabel("Avg ad density (% of viewport)")
    ax.set_title("Ad Density by Website Category", fontsize=14, fontweight="bold")
    for bar, val in zip(bars, densities):
        ax.text(bar.get_x() + bar.get_width()/2, val + 0.2, f"{val}%", ha="center", fontsize=10)

    plt.tight_layout()
    fig.savefig(out / "ad_density_by_category.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'ad_density_by_category.png'}")


# ─── Chart 14: Ad density vs tracker count ───────────────────────────

def chart_ad_density_vs_trackers(conn: sqlite3.Connection, out: Path) -> None:
    """Scatter plot: correlation between ad density and number of trackers."""
    rows = conn.execute("""
        SELECT cs.ad_density * 100 as density, cs.third_party_requests as trackers,
               s.category
        FROM crawl_sessions cs JOIN sites s ON cs.site_id = s.id
        WHERE cs.consent_mode='ignore' AND cs.status='success' AND cs.ad_density > 0
    """).fetchall()
    if not rows:
        return

    densities = [r["density"] for r in rows]
    trackers = [r["trackers"] for r in rows]

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(trackers, densities, alpha=0.6, color="#e74c3c", edgecolors="#c0392b", linewidth=0.5)
    ax.set_xlabel("3rd-party requests")
    ax.set_ylabel("Ad density (% of viewport)")
    ax.set_title("More Trackers = More Ads?", fontsize=14, fontweight="bold")

    plt.tight_layout()
    fig.savefig(out / "ad_density_vs_trackers.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'ad_density_vs_trackers.png'}")


# ─── Chart 15: Resource weight breakdown ─────────────────────────────

def chart_resource_weight_breakdown(conn: sqlite3.Connection, out: Path) -> None:
    """Stacked bar per site category: bytes by resource category."""
    rows = conn.execute("""
        SELECT s.category,
               ROUND(AVG(cs.rw_content_1p_bytes) / 1024.0, 0) as content_kb,
               ROUND(AVG(cs.rw_cdn_bytes) / 1024.0, 0) as cdn_kb,
               ROUND(AVG(cs.rw_tracker_bytes) / 1024.0, 0) as tracker_kb,
               ROUND(AVG(cs.rw_ad_bytes) / 1024.0, 0) as ad_kb,
               ROUND(AVG(cs.rw_functional_3p_bytes) / 1024.0, 0) as func_kb,
               ROUND(AVG(cs.rw_unknown_3p_bytes) / 1024.0, 0) as unk_kb
        FROM crawl_sessions cs JOIN sites s ON cs.site_id = s.id
        WHERE cs.consent_mode='ignore' AND cs.status='success' AND cs.rw_total_bytes > 0
        GROUP BY s.category ORDER BY AVG(cs.rw_total_bytes) DESC
    """).fetchall()
    if not rows:
        return

    cats = [r["category"] for r in rows]
    content = [r["content_kb"] or 0 for r in rows]
    cdn = [r["cdn_kb"] or 0 for r in rows]
    tracker = [r["tracker_kb"] or 0 for r in rows]
    ad = [r["ad_kb"] or 0 for r in rows]
    func = [r["func_kb"] or 0 for r in rows]
    unk = [r["unk_kb"] or 0 for r in rows]

    fig, ax = plt.subplots(figsize=(12, 6))
    x = range(len(cats))
    ax.bar(x, content, label="Content (1P)", color="#2ecc71")
    ax.bar(x, cdn, bottom=content, label="CDN", color="#3498db")
    bottom2 = [c + d for c, d in zip(content, cdn)]
    ax.bar(x, tracker, bottom=bottom2, label="Tracker", color="#e74c3c")
    bottom3 = [b + t for b, t in zip(bottom2, tracker)]
    ax.bar(x, ad, bottom=bottom3, label="Advertising", color="#f39c12")
    bottom4 = [b + a for b, a in zip(bottom3, ad)]
    ax.bar(x, func, bottom=bottom4, label="Functional 3P", color="#9b59b6")
    bottom5 = [b + f for b, f in zip(bottom4, func)]
    ax.bar(x, unk, bottom=bottom5, label="Unknown 3P", color="#95a5a6")

    ax.set_xticks(list(x))
    ax.set_xticklabels(cats, fontsize=9, rotation=30, ha="right")
    ax.set_ylabel("Avg KB per page")
    ax.set_title("What Makes Up a Czech Webpage?", fontsize=14, fontweight="bold")
    ax.legend(loc="upper right")

    plt.tight_layout()
    fig.savefig(out / "resource_weight_breakdown.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'resource_weight_breakdown.png'}")


# ─── Chart 16: Resource weight pie chart ─────────────────────────────

def chart_resource_weight_pie(conn: sqlite3.Connection, out: Path) -> None:
    """Pie chart: average byte distribution across all sites."""
    row = conn.execute("""
        SELECT SUM(rw_content_1p_bytes) as content,
               SUM(rw_cdn_bytes) as cdn,
               SUM(rw_tracker_bytes) as tracker,
               SUM(rw_ad_bytes) as ad,
               SUM(rw_functional_3p_bytes) as func,
               SUM(rw_unknown_3p_bytes) as unk
        FROM crawl_sessions
        WHERE status='success' AND consent_mode='ignore' AND rw_total_bytes > 0
    """).fetchone()
    if not row or not row["content"]:
        return

    labels = ["Content", "CDN", "Tracker", "Ad", "Functional 3P", "Unknown 3P"]
    sizes = [row["content"] or 0, row["cdn"] or 0, row["tracker"] or 0,
             row["ad"] or 0, row["func"] or 0, row["unk"] or 0]
    colors = ["#2ecc71", "#3498db", "#e74c3c", "#f39c12", "#9b59b6", "#95a5a6"]

    # Filter out zero segments
    filtered = [(l, s, c) for l, s, c in zip(labels, sizes, colors) if s > 0]
    if not filtered:
        return
    labels, sizes, colors = zip(*filtered)

    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct="%1.1f%%",
        colors=colors, startangle=90, pctdistance=0.85,
    )
    for text in autotexts:
        text.set_fontsize(10)
    ax.set_title("Where Does Bandwidth Go on Czech Websites?", fontsize=14, fontweight="bold")

    plt.tight_layout()
    fig.savefig(out / "resource_weight_pie.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'resource_weight_pie.png'}")


# ─── Chart 17: Tracker bandwidth by entity ───────────────────────────

def chart_tracker_bandwidth_by_entity(conn: sqlite3.Connection, out: Path) -> None:
    """Bar: which tracker entities consume the most bandwidth."""
    rows = conn.execute("""
        SELECT r.tracker_entity,
               SUM(r.response_size_bytes) / 1024 as total_kb
        FROM requests r
        JOIN crawl_sessions cs ON r.session_id = cs.id
        WHERE r.tracker_entity IS NOT NULL AND cs.consent_mode='ignore'
              AND cs.status='success' AND r.response_size_bytes > 0
        GROUP BY r.tracker_entity
        ORDER BY total_kb DESC LIMIT 15
    """).fetchall()
    if not rows:
        return

    entities = [r["tracker_entity"] for r in rows][::-1]
    kb = [r["total_kb"] for r in rows][::-1]

    fig, ax = plt.subplots(figsize=(10, 7))
    colors_map = {
        "Google": "#4285F4", "Meta": "#1877F2", "Seznam.cz": "#cc0000",
        "Microsoft": "#00a4ef", "Amazon": "#FF9900", "Criteo": "#f5811f",
        "Adform": "#6c5ce7", "Gemius": "#00b894",
    }
    bar_colors = [colors_map.get(e, "#636e72") for e in entities]

    bars = ax.barh(entities, kb, color=bar_colors, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Total KB transferred")
    ax.set_title("Bandwidth Cost of Surveillance", fontsize=14, fontweight="bold")

    for bar, val in zip(bars, kb):
        ax.text(val + 10, bar.get_y() + bar.get_height()/2,
                f"{val:,.0f} KB", va="center", fontsize=9)

    plt.tight_layout()
    fig.savefig(out / "tracker_bandwidth_by_entity.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'tracker_bandwidth_by_entity.png'}")


# ─── Chart 18: Resource weight vs consent mode ───────────────────────

def chart_resource_weight_vs_consent(conn: sqlite3.Connection, out: Path) -> None:
    """Grouped bar: does accepting cookies increase page weight?"""
    rows = conn.execute("""
        SELECT consent_mode,
               ROUND(AVG(rw_total_bytes) / 1024.0, 0) as avg_total_kb,
               ROUND(AVG(rw_tracker_bytes + rw_ad_bytes) / 1024.0, 0) as avg_tracking_kb,
               ROUND(AVG(rw_content_1p_bytes) / 1024.0, 0) as avg_content_kb
        FROM crawl_sessions
        WHERE status='success' AND rw_total_bytes > 0
        GROUP BY consent_mode ORDER BY consent_mode
    """).fetchall()
    if not rows:
        return

    modes = [r["consent_mode"] for r in rows]
    total_kb = [r["avg_total_kb"] or 0 for r in rows]
    tracking_kb = [r["avg_tracking_kb"] or 0 for r in rows]
    content_kb = [r["avg_content_kb"] or 0 for r in rows]

    x = range(len(modes))
    width = 0.25

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar([i - width for i in x], total_kb, width, label="Total", color="#2c3e50")
    ax.bar(list(x), tracking_kb, width, label="Tracker + Ad", color="#e74c3c")
    ax.bar([i + width for i in x], content_kb, width, label="Content", color="#2ecc71")

    ax.set_xticks(list(x))
    ax.set_xticklabels(modes)
    ax.set_ylabel("Avg KB per page")
    ax.set_title("Does Accepting Cookies Increase Page Weight?", fontsize=14, fontweight="bold")
    ax.legend()

    plt.tight_layout()
    fig.savefig(out / "resource_weight_vs_consent.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  -> {out / 'resource_weight_vs_consent.png'}")


# ─── Phase 2 CSV exports ─────────────────────────────────────────────

def export_csv_phase2(conn: sqlite3.Connection, out: Path) -> None:
    """Export Phase 2 tables as CSV."""
    exports = {
        "fingerprint_events.csv": """
            SELECT fe.api, fe.method, fe.call_stack_domain, fe.tracker_entity,
                   fe.details, fe.timestamp,
                   s.domain as site_domain, cs.consent_mode
            FROM fingerprint_events fe
            JOIN crawl_sessions cs ON fe.session_id = cs.id
            JOIN sites s ON cs.site_id = s.id
            WHERE cs.status='success'
            ORDER BY s.domain, cs.consent_mode
        """,
        "fingerprint_summary.csv": """
            SELECT s.domain, s.category, cs.consent_mode,
                   cs.fp_severity, cs.fp_event_count,
                   cs.fp_canvas, cs.fp_webgl, cs.fp_audio,
                   cs.fp_font, cs.fp_navigator, cs.fp_storage,
                   cs.fp_unique_apis, cs.fp_unique_entities
            FROM crawl_sessions cs
            JOIN sites s ON cs.site_id = s.id
            WHERE cs.status='success' AND cs.fp_severity IS NOT NULL
            ORDER BY s.domain, cs.consent_mode
        """,
        "ad_elements.csv": """
            SELECT s.domain, s.category, cs.consent_mode,
                   ae.selector, ae.tag_name, ae.ad_id,
                   ae.width, ae.height, ae.iab_size, ae.ad_network,
                   ae.is_iframe, ae.iframe_src
            FROM ad_elements ae
            JOIN crawl_sessions cs ON ae.session_id = cs.id
            JOIN sites s ON cs.site_id = s.id
            WHERE cs.status='success'
            ORDER BY s.domain, cs.consent_mode
        """,
        "resource_weight_by_session.csv": """
            SELECT s.domain, s.category, cs.consent_mode,
                   cs.rw_total_bytes, cs.rw_content_1p_bytes,
                   cs.rw_cdn_bytes, cs.rw_tracker_bytes, cs.rw_ad_bytes,
                   cs.rw_functional_3p_bytes, cs.rw_unknown_3p_bytes
            FROM crawl_sessions cs
            JOIN sites s ON cs.site_id = s.id
            WHERE cs.status='success' AND cs.rw_total_bytes > 0
            ORDER BY s.domain, cs.consent_mode
        """,
        "resource_weight_by_entity.csv": """
            SELECT r.tracker_entity, r.resource_category,
                   COUNT(*) as request_count,
                   SUM(r.response_size_bytes) as total_bytes,
                   COUNT(DISTINCT cs.site_id) as sites
            FROM requests r
            JOIN crawl_sessions cs ON r.session_id = cs.id
            WHERE r.tracker_entity IS NOT NULL AND cs.consent_mode='ignore'
                  AND cs.status='success'
            GROUP BY r.tracker_entity, r.resource_category
            ORDER BY total_bytes DESC
        """,
    }

    csv_dir = out / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    for filename, query in exports.items():
        try:
            rows = conn.execute(query).fetchall()
        except sqlite3.OperationalError:
            continue
        if not rows:
            continue
        filepath = csv_dir / filename
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(rows[0].keys())
            writer.writerows(rows)
        print(f"  -> {filepath} ({len(rows)} rows)")


# ─── Ad gallery (HTML) ───────────────────────────────────────────────

def generate_ad_gallery(conn: sqlite3.Connection, out: Path) -> None:
    """Generate a self-contained HTML gallery of all captured ad screenshots."""
    rows = conn.execute("""
        SELECT ac.screenshot_path, ac.width, ac.height, ac.capture_method,
               ae.ad_network, ae.iab_size, ae.tag_name,
               s.domain, s.category, cs.consent_mode
        FROM ad_captures ac
        JOIN crawl_sessions cs ON ac.session_id = cs.id
        JOIN sites s ON cs.site_id = s.id
        LEFT JOIN ad_elements ae ON ac.ad_element_id = ae.id
        WHERE ac.screenshot_path IS NOT NULL AND ac.capture_method != 'failed'
        ORDER BY s.domain, cs.consent_mode
    """).fetchall()

    if not rows:
        return

    # Build HTML
    cards_html = []
    networks = set()
    for r in rows:
        network = r["ad_network"] or "unknown"
        networks.add(network)
        size_label = r["iab_size"] or f"{r['width']}x{r['height']}"
        cards_html.append(f"""
        <div class="card" data-network="{network}" data-consent="{r['consent_mode']}"
             data-site="{r['domain']}">
            <img src="../../{r['screenshot_path']}" alt="Ad from {r['domain']}"
                 loading="lazy" onclick="this.classList.toggle('enlarged')">
            <div class="meta">
                <strong>{r['domain']}</strong> [{r['consent_mode']}]<br>
                {network} &middot; {size_label} &middot; {r['tag_name']}
            </div>
        </div>""")

    filter_buttons = "".join(
        f'<button onclick="filterNetwork(\'{n}\')">{n}</button>' for n in sorted(networks)
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Ad Gallery — Footprint Crawler</title>
<style>
body {{ font-family: -apple-system, sans-serif; background: #1a1a2e; color: #eee; margin: 0; padding: 20px; }}
h1 {{ text-align: center; }}
.stats {{ text-align: center; margin: 10px 0; color: #aaa; }}
.filters {{ text-align: center; margin: 15px 0; }}
.filters button {{ background: #333; color: #eee; border: 1px solid #555; padding: 5px 12px;
    margin: 3px; cursor: pointer; border-radius: 4px; }}
.filters button:hover, .filters button.active {{ background: #e74c3c; border-color: #e74c3c; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; padding: 20px 0; }}
.card {{ background: #16213e; border-radius: 8px; overflow: hidden; transition: 0.2s; }}
.card.hidden {{ display: none; }}
.card img {{ width: 100%; display: block; cursor: pointer; transition: 0.2s; }}
.card img.enlarged {{ position: fixed; top: 50%; left: 50%; transform: translate(-50%,-50%);
    width: auto; max-width: 90vw; max-height: 90vh; z-index: 999; box-shadow: 0 0 50px rgba(0,0,0,0.8); }}
.meta {{ padding: 8px; font-size: 12px; color: #aaa; }}
</style></head><body>
<h1>Ad Specimen Collection</h1>
<div class="stats">{len(rows)} ads captured from Czech websites</div>
<div class="filters">
    <button onclick="filterNetwork('all')" class="active">All</button>
    {filter_buttons}
</div>
<div class="grid">{''.join(cards_html)}</div>
<script>
function filterNetwork(net) {{
    document.querySelectorAll('.card').forEach(c => {{
        c.classList.toggle('hidden', net !== 'all' && c.dataset.network !== net);
    }});
    document.querySelectorAll('.filters button').forEach(b => {{
        b.classList.toggle('active', b.textContent === net || (net === 'all' && b.textContent === 'All'));
    }});
}}
</script></body></html>"""

    gallery_path = out / "ad_gallery.html"
    with open(gallery_path, "w") as f:
        f.write(html)
    print(f"  -> {gallery_path} ({len(rows)} ads)")


# ─── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Footprint Crawler — Visualize crawl results")
    parser.add_argument("--db", default=DB_PATH, help="Path to SQLite database")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Output directory for charts")
    parser.add_argument("--report", action="store_true", help="Print text report only")
    parser.add_argument("--export-csv", action="store_true", help="Export CSV files")
    parser.add_argument("--export-graph", action="store_true", help="Export network graph JSON")
    parser.add_argument("--all", action="store_true", help="Generate everything")
    args = parser.parse_args()

    conn = get_conn(args.db)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if args.report:
        print_report(conn)
        conn.close()
        return

    generate_charts = not args.export_csv and not args.export_graph or args.all
    do_csv = args.export_csv or args.all
    do_graph = args.export_graph or args.all

    if generate_charts or args.all or (not args.export_csv and not args.export_graph):
        print("\nGenerating Phase 1 charts...")
        chart_consent_comparison(conn, out)
        chart_top_trackers(conn, out)
        chart_tracking_by_category(conn, out)
        chart_pre_post_consent(conn, out)
        chart_cmp_distribution(conn, out)
        chart_top_tracked_sites(conn, out)
        chart_cookie_lifetimes(conn, out)

        print("\nGenerating Phase 2 charts...")
        chart_fingerprint_severity(conn, out)
        chart_fingerprint_vectors(conn, out)
        chart_fingerprint_vs_consent(conn, out)
        chart_ad_density_distribution(conn, out)
        chart_ad_network_reach(conn, out)
        chart_ad_density_by_category(conn, out)
        chart_ad_density_vs_trackers(conn, out)
        chart_resource_weight_breakdown(conn, out)
        chart_resource_weight_pie(conn, out)
        chart_tracker_bandwidth_by_entity(conn, out)
        chart_resource_weight_vs_consent(conn, out)

        print("\nGenerating ad gallery...")
        generate_ad_gallery(conn, out)

    if do_csv:
        print("\nExporting CSV files...")
        export_csv(conn, out)
        export_csv_phase2(conn, out)

    if do_graph:
        print("\nExporting network graph...")
        export_network_graph(conn, out)

    if args.all:
        print("\nText report:")
        print_report(conn)

    conn.close()
    print(f"\nDone! Output in: {out}/")


if __name__ == "__main__":
    main()
