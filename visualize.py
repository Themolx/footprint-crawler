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
        print("\nGenerating charts...")
        chart_consent_comparison(conn, out)
        chart_top_trackers(conn, out)
        chart_tracking_by_category(conn, out)
        chart_pre_post_consent(conn, out)
        chart_cmp_distribution(conn, out)
        chart_top_tracked_sites(conn, out)
        chart_cookie_lifetimes(conn, out)

    if do_csv:
        print("\nExporting CSV files...")
        export_csv(conn, out)

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
