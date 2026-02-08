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

# ANSI color codes
_DIM = "\033[2m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_MAGENTA = "\033[35m"
_RESET = "\033[0m"
_CLEAR_LINE = "\033[2K\r"


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
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable colored output",
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


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m"


def _bar(current: int, total: int, width: int = 20) -> str:
    """Simple ASCII progress bar."""
    if total == 0:
        return "[" + " " * width + "]"
    filled = int(width * current / total)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


class ProgressDisplay:
    """Live progress display for the crawl."""

    def __init__(self, total_tasks: int, use_color: bool = True):
        self.total = total_tasks
        self.completed = 0
        self.errors = 0
        self.total_requests = 0
        self.total_cookies = 0
        self.total_3p = 0
        self.total_tracking = 0
        self.banners_detected = 0
        self.banners_acted = 0
        self.start_time = time.monotonic()
        self.use_color = use_color
        self._active_tasks: dict[str, str] = {}  # domain -> phase
        self._lock = asyncio.Lock()

    def _c(self, code: str, text: str) -> str:
        if not self.use_color:
            return text
        return f"{code}{text}{_RESET}"

    def _status_line(self) -> str:
        elapsed = time.monotonic() - self.start_time
        rate = self.completed / elapsed if elapsed > 0 else 0
        eta = (self.total - self.completed) / rate if rate > 0 else 0

        pct = (self.completed / self.total * 100) if self.total > 0 else 0
        bar = _bar(self.completed, self.total)

        parts = [
            f"{bar} {pct:>5.1f}%",
            f"{self.completed}/{self.total} done",
        ]
        if self.errors:
            parts.append(self._c(_RED, f"{self.errors} err"))
        parts.append(f"ETA {_format_duration(eta)}")

        active_count = len(self._active_tasks)
        if active_count > 0:
            # Show up to 3 active domains
            active_names = list(self._active_tasks.keys())[:3]
            active_str = ", ".join(active_names)
            if active_count > 3:
                active_str += f" +{active_count - 3}"
            parts.append(self._c(_DIM, f"active: {active_str}"))

        return "  ".join(parts)

    def update_active(self, domain: str, phase: str, detail: str = "") -> None:
        """Update the phase display for an active task."""
        self._active_tasks[domain] = f"{phase}" + (f" {detail}" if detail else "")
        # Print status line
        sys.stdout.write(_CLEAR_LINE + self._status_line())
        sys.stdout.flush()

    def remove_active(self, domain: str) -> None:
        self._active_tasks.pop(domain, None)

    def print_result(self, result: CrawlResult) -> None:
        """Print a completed task result on its own line."""
        self.completed += 1
        req_count = len(result.requests)
        third_party = sum(1 for r in result.requests if r.is_third_party)
        cookie_count = len(result.cookies)
        tracking = sum(1 for c in result.cookies if c.is_tracking_cookie)

        self.total_requests += req_count
        self.total_3p += third_party
        self.total_cookies += cookie_count
        self.total_tracking += tracking

        if result.status != CrawlStatus.SUCCESS:
            self.errors += 1

        consent = result.consent_info
        if consent and consent.banner_detected:
            self.banners_detected += 1
            if consent.action_taken:
                self.banners_acted += 1

        # Format the completed line
        elapsed_s = 0
        try:
            from datetime import datetime, timezone
            start = datetime.fromisoformat(result.started_at)
            end = datetime.fromisoformat(result.completed_at)
            elapsed_s = (end - start).total_seconds()
        except Exception:
            pass

        # Status indicator
        if result.status == CrawlStatus.SUCCESS:
            status = self._c(_GREEN, "OK")
        elif result.status == CrawlStatus.TIMEOUT:
            status = self._c(_YELLOW, "TIMEOUT")
        else:
            status = self._c(_RED, "ERROR")

        # Mode with color
        mode_colors = {
            ConsentMode.IGNORE: _DIM,
            ConsentMode.ACCEPT: _CYAN,
            ConsentMode.REJECT: _MAGENTA,
        }
        mode_str = self._c(mode_colors.get(result.consent_mode, ""), result.consent_mode.value)

        # Domain + category
        domain = result.site.domain
        cat = result.site.category or ""
        cat_str = self._c(_DIM, f"[{cat}]") if cat else ""

        # Consent info
        consent_str = ""
        if consent and consent.banner_detected:
            cmp = consent.cmp_platform or "?"
            if consent.action_taken:
                consent_str = self._c(_GREEN, f" banner:{cmp}")
            else:
                consent_str = self._c(_YELLOW, f" banner:{cmp}(no click)")
        elif result.consent_mode != ConsentMode.IGNORE:
            consent_str = self._c(_DIM, " no banner")

        # Request breakdown
        req_str = f"{req_count:>4} req"
        if third_party > 0:
            req_str += self._c(_YELLOW, f" ({third_party} 3p)")
        else:
            req_str += self._c(_DIM, " (0 3p)")

        # Cookie breakdown
        cook_str = f"{cookie_count:>2} cookies"
        if tracking > 0:
            cook_str += self._c(_RED, f" ({tracking} trk)")
        else:
            cook_str += self._c(_DIM, " (0 trk)")

        # Clear status line and print result
        sys.stdout.write(_CLEAR_LINE)
        print(
            f"  {self._c(_DIM, f'{self.completed:>4}.')} "
            f"{status:<8} "
            f"{domain:<28} {mode_str:<8} "
            f"{cat_str:<14} "
            f"{req_str}  {cook_str}"
            f"{consent_str}"
            f"  {self._c(_DIM, _format_duration(elapsed_s))}"
        )

        # Print updated status line
        sys.stdout.write(self._status_line())
        sys.stdout.flush()

    def print_header(self, config: CrawlerConfig, sites_count: int, modes: list[ConsentMode]) -> None:
        """Print the crawl header."""
        print()
        print(self._c(_BOLD, "  FOOTPRINT CRAWLER — Czech Internet Tracking Observatory"))
        print(self._c(_DIM, "  " + "=" * 60))
        print(f"  Sites: {sites_count}  |  Modes: {', '.join(m.value for m in modes)}  |  "
              f"Tasks: {self.total}")
        print(f"  Concurrency: {config.crawler.concurrency}  |  "
              f"Post-consent dwell: {config.crawler.post_consent_wait_ms // 1000}s  |  "
              f"Headless: {config.crawler.headless}")
        print(self._c(_DIM, "  " + "-" * 60))
        print()

    def print_summary(self, db_path: Path) -> None:
        """Print the final summary."""
        elapsed = time.monotonic() - self.start_time
        print()
        print()
        print(self._c(_BOLD, "  CRAWL COMPLETE"))
        print(self._c(_DIM, "  " + "=" * 60))
        print()
        print(f"  Duration        {_format_duration(elapsed)}")
        print(f"  Tasks           {self.completed}/{self.total}"
              + (self._c(_RED, f" ({self.errors} errors)") if self.errors else self._c(_GREEN, " (0 errors)")))
        print()
        print(f"  Requests        {self.total_requests:,} total")
        print(f"  3rd-party       {self.total_3p:,}" + self._c(_DIM, f" ({self.total_3p * 100 // max(self.total_requests, 1)}% of all)"))
        print(f"  Cookies         {self.total_cookies:,} total")
        print(f"  Tracking        {self.total_tracking:,} tracking cookies")
        print()
        print(f"  Banners found   {self.banners_detected}")
        print(f"  Banners clicked {self.banners_acted}")
        print()
        print(f"  Database        {db_path}")
        print(self._c(_DIM, "  " + "=" * 60))
        print()


async def main(args: argparse.Namespace) -> None:
    """Main crawl orchestration loop."""
    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
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

    use_color = not args.no_color

    # Parse consent modes
    mode_names = [m.strip().lower() for m in args.modes.split(",")]
    modes: list[ConsentMode] = []
    for name in mode_names:
        try:
            modes.append(ConsentMode(name))
        except ValueError:
            print(f"Unknown consent mode: {name}", file=sys.stderr)
            sys.exit(1)

    # Load sites
    sites_path = config.resolve_path(args.sites or config.sites_file)
    if not sites_path.exists():
        print(f"Sites file not found: {sites_path}", file=sys.stderr)
        sys.exit(1)

    sites = load_sites_csv(sites_path)
    if args.limit:
        sites = sites[: args.limit]

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
    skipped = 0
    for site in sites:
        for mode in modes:
            if args.resume and await db.has_session(site.domain, mode.value):
                skipped += 1
                continue
            tasks.append((site, mode))

    if not tasks:
        print("No tasks to run (all sites already crawled). Use without --resume to re-crawl.")
        await db.close()
        return

    # Set up progress display
    progress = ProgressDisplay(len(tasks), use_color=use_color)
    progress.print_header(config, len(sites), modes)

    if skipped > 0:
        print(f"  Skipped {skipped} already-crawled tasks (--resume)")
        print()

    # Launch Playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.crawler.headless)

        sem = asyncio.Semaphore(config.crawler.concurrency)

        async def run_task(site: SiteInfo, mode: ConsentMode) -> None:
            async with sem:
                task_key = f"{site.domain}:{mode.value}"

                def on_progress(phase: str, detail: str = "") -> None:
                    progress.update_active(task_key, phase, detail)

                for attempt in range(config.crawler.max_retries + 1):
                    progress.update_active(task_key, "loading" if attempt == 0 else f"retry #{attempt + 1}")

                    result = await crawl_site(
                        browser, site, mode, config,
                        tracker_db, consent_handler,
                        on_progress=on_progress,
                    )

                    if result.status == CrawlStatus.SUCCESS or attempt >= config.crawler.max_retries:
                        break
                    await asyncio.sleep(2)

                try:
                    await db.save_crawl_result(result)
                except Exception as e:
                    logger.error("Failed to save result for %s (%s): %s",
                                 site.domain, mode.value, e)

                progress.remove_active(task_key)
                progress.print_result(result)

                # Rate limiting
                await asyncio.sleep(config.crawler.inter_site_delay_ms / 1000)

        # Run all tasks concurrently (bounded by semaphore)
        await asyncio.gather(*(run_task(s, m) for s, m in tasks))

        await browser.close()

    # Final summary
    await db.close()
    progress.print_summary(db_path)
