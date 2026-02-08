"""CLI entry point and crawl orchestration."""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

from .config import CrawlerConfig, load_config
from .consent import ConsentHandler
from .db import Database
from .engine import crawl_site
from .models import ConsentMode, CrawlStatus, SiteInfo
from .tracker_db import TrackerDatabase
from .utils import normalize_url

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="footprint_crawler",
        description="Footprint Crawler — Czech Internet Tracking Observatory",
    )
    parser.add_argument(
        "--config", type=str, default="config.yaml",
        help="Path to config.yaml (default: ./config.yaml)",
    )
    parser.add_argument(
        "--sites", type=str, default=None,
        help="Override sites CSV file path",
    )
    parser.add_argument(
        "--concurrency", type=int, default=None,
        help="Override number of concurrent browser contexts",
    )
    parser.add_argument(
        "--modes", type=str, default="ignore,accept,reject",
        help="Comma-separated consent modes to run (default: ignore,accept,reject)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only crawl first N sites (for testing)",
    )
    parser.add_argument(
        "--headed", action="store_true",
        help="Run in headed mode (visible browser windows)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip sites/modes already crawled successfully",
    )
    return parser.parse_args(argv)


def load_sites_csv(path: Path) -> list[SiteInfo]:
    """Load sites from a CSV file."""
    sites: list[SiteInfo] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = normalize_url(row["url"])
            domain = row.get("domain", "").strip()
            category = row.get("category", "").strip() or None
            rank_str = row.get("rank_cz", "").strip()
            rank = int(rank_str) if rank_str else None
            sites.append(SiteInfo(url=url, domain=domain, category=category, rank_cz=rank))
    return sites


def _format_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m"


async def main(args: argparse.Namespace) -> None:
    """Main crawl orchestration loop."""
    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy loggers
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # Load config
    config_path = Path(args.config).resolve()
    config = load_config(config_path)

    # Apply CLI overrides
    if args.concurrency:
        config.crawler.concurrency = args.concurrency
    if args.headed:
        config.crawler.headless = False

    # Parse consent modes
    mode_names = [m.strip().lower() for m in args.modes.split(",")]
    modes: list[ConsentMode] = []
    for name in mode_names:
        try:
            modes.append(ConsentMode(name))
        except ValueError:
            logger.error("Unknown consent mode: %s", name)
            sys.exit(1)

    # Load sites
    sites_path = config.resolve_path(args.sites or config.sites_file)
    if not sites_path.exists():
        logger.error("Sites file not found: %s", sites_path)
        sys.exit(1)

    sites = load_sites_csv(sites_path)
    if args.limit:
        sites = sites[: args.limit]

    logger.info("Loaded %d sites, modes: %s, concurrency: %d",
                len(sites), [m.value for m in modes], config.crawler.concurrency)

    # Initialize database
    db_path = config.resolve_path(config.database.path)
    db = Database(db_path)
    await db.connect()

    # Initialize tracker database
    czech_trackers_path = config.resolve_path("data/trackers/czech_trackers.json")
    disconnect_path = config.resolve_path("data/trackers/disconnect.json")
    tracker_db = TrackerDatabase(
        disconnect_path=str(disconnect_path) if disconnect_path.exists() else None,
        czech_trackers_path=str(czech_trackers_path) if czech_trackers_path.exists() else None,
    )

    # Initialize consent handler
    consent_handler = ConsentHandler(config.consent_patterns)

    # Insert sites into database
    for site in sites:
        await db.upsert_site(site)

    # Build task list
    tasks: list[tuple[SiteInfo, ConsentMode]] = []
    for site in sites:
        for mode in modes:
            if args.resume and await db.has_session(site.domain, mode.value):
                logger.debug("Skipping %s (%s) — already crawled", site.domain, mode.value)
                continue
            tasks.append((site, mode))

    if not tasks:
        logger.info("No tasks to run (all sites already crawled). Use without --resume to re-crawl.")
        await db.close()
        return

    total = len(tasks)
    logger.info("Starting crawl: %d tasks (%d sites x %d modes)",
                total, len(sites), len(modes))

    # Launch Playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.crawler.headless)
        logger.info("Browser launched (headless=%s)", config.crawler.headless)

        sem = asyncio.Semaphore(config.crawler.concurrency)
        completed = 0
        errors = 0
        total_requests_captured = 0
        total_cookies_captured = 0
        crawl_start = time.monotonic()

        async def run_task(site: SiteInfo, mode: ConsentMode) -> None:
            nonlocal completed, errors, total_requests_captured, total_cookies_captured

            async with sem:
                for attempt in range(config.crawler.max_retries + 1):
                    result = await crawl_site(
                        browser, site, mode, config,
                        tracker_db, consent_handler,
                    )

                    if result.status == CrawlStatus.SUCCESS or attempt >= config.crawler.max_retries:
                        break

                    logger.info("Retrying %s (%s) — attempt %d/%d",
                                site.domain, mode.value, attempt + 2, config.crawler.max_retries + 1)
                    await asyncio.sleep(1)

                try:
                    await db.save_crawl_result(result)
                except Exception as e:
                    logger.error("Failed to save result for %s (%s): %s",
                                 site.domain, mode.value, e)

                completed += 1
                total_requests_captured += len(result.requests)
                total_cookies_captured += len(result.cookies)

                if result.status != CrawlStatus.SUCCESS:
                    errors += 1

                # Progress output
                elapsed = time.monotonic() - crawl_start
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total - completed) / rate if rate > 0 else 0

                third_party = sum(1 for r in result.requests if r.is_third_party)
                tracking = sum(1 for c in result.cookies if c.is_tracking_cookie)

                status_icon = "OK" if result.status == CrawlStatus.SUCCESS else result.status.value.upper()
                consent_str = ""
                if result.consent_info and result.consent_info.banner_detected:
                    cmp = result.consent_info.cmp_platform or "?"
                    acted = "Y" if result.consent_info.action_taken else "N"
                    consent_str = f" [CMP:{cmp} acted:{acted}]"

                print(
                    f"[{completed:>4}/{total}] {status_icon:<7} "
                    f"{site.domain:<30} ({mode.value:<6}) "
                    f"| {len(result.requests):>3} req ({third_party} 3p), "
                    f"{len(result.cookies):>2} cookies ({tracking} trk)"
                    f"{consent_str}"
                )

                # Rate limiting
                await asyncio.sleep(config.crawler.inter_site_delay_ms / 1000)

        # Run all tasks concurrently (bounded by semaphore)
        await asyncio.gather(*(run_task(s, m) for s, m in tasks))

        await browser.close()

    # Final summary
    elapsed = time.monotonic() - crawl_start
    stats = await db.get_stats()
    await db.close()

    print("\n" + "=" * 70)
    print("CRAWL COMPLETE")
    print("=" * 70)
    print(f"  Duration:           {_format_eta(elapsed)}")
    print(f"  Tasks:              {completed}/{total} ({errors} errors)")
    print(f"  Requests captured:  {total_requests_captured:,}")
    print(f"  Cookies captured:   {total_cookies_captured:,}")
    print(f"  3rd-party requests: {stats.get('third_party_requests', 0):,}")
    print(f"  Database:           {db.db_path}")
    print("=" * 70)
