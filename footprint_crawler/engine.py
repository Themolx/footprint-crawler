"""Core Playwright crawl engine.

Handles a single (site, consent_mode) crawl: creates a fresh browser context,
navigates, intercepts requests, handles consent, dwells for 60s to capture
cascading tracker activity, scrolls, captures cookies, and returns a CrawlResult.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from playwright.async_api import Browser, Dialog, Request as PWRequest, Response as PWResponse

from .config import CrawlerConfig
from .consent import ConsentHandler
from .models import (
    ConsentInfo,
    ConsentMode,
    CookieRecord,
    CrawlResult,
    CrawlStatus,
    RequestRecord,
    SiteInfo,
)
from .tracker_db import TrackerDatabase
from .utils import (
    extract_hostname,
    extract_registered_domain,
    hash_cookie_value,
    is_third_party,
    now_iso,
)

logger = logging.getLogger(__name__)


# Callback type for live progress reporting
ProgressCallback = None  # will be a callable if provided


async def crawl_site(
    browser: Browser,
    site: SiteInfo,
    mode: ConsentMode,
    config: CrawlerConfig,
    tracker_db: TrackerDatabase,
    consent_handler: ConsentHandler,
    on_progress: callable | None = None,
) -> CrawlResult:
    """Crawl a single site in the specified consent mode.

    Creates a fresh browser context, navigates to the site, intercepts all
    requests, handles cookie consent, dwells to let trackers cascade,
    scrolls, and captures all tracking data.

    Args:
        on_progress: Optional callback(phase, detail) for live status updates.
    """
    started_at = now_iso()
    start_time = time.monotonic()
    captured_requests: list[RequestRecord] = []
    site_reg_domain = extract_registered_domain(site.url)

    # Request count at various phases
    pre_consent_request_count = 0
    post_consent_request_count = 0

    def _notify(phase: str, detail: str = "") -> None:
        if on_progress:
            on_progress(phase, detail)

    context = None
    try:
        # Create fresh browser context
        context = await browser.new_context(
            locale=config.browser.locale,
            timezone_id=config.browser.timezone,
            geolocation={
                "latitude": config.browser.geolocation.latitude,
                "longitude": config.browser.geolocation.longitude,
            },
            permissions=["geolocation"],
            viewport={
                "width": config.browser.viewport.width,
                "height": config.browser.viewport.height,
            },
            user_agent=config.browser.user_agent or None,
        )

        page = await context.new_page()

        # Auto-dismiss JavaScript dialogs (alerts, confirms, prompts)
        async def _handle_dialog(dialog: Dialog) -> None:
            logger.debug("Auto-dismissing %s dialog on %s", dialog.type, site.domain)
            try:
                await dialog.dismiss()
            except Exception:
                pass

        page.on("dialog", _handle_dialog)

        # Set up request interception BEFORE navigation
        request_timestamps: dict[str, float] = {}

        def on_request(request: PWRequest) -> None:
            req_domain = extract_hostname(request.url)
            req_reg_domain = extract_registered_domain(request.url)
            third_party = is_third_party(req_domain, site_reg_domain)
            entity, category = tracker_db.classify(req_reg_domain)

            record = RequestRecord(
                url=request.url,
                domain=req_reg_domain,
                method=request.method,
                resource_type=request.resource_type,
                is_third_party=third_party,
                tracker_entity=entity,
                tracker_category=category,
                timestamp=now_iso(),
            )
            captured_requests.append(record)
            request_timestamps[request.url] = time.monotonic()

        def on_response(response: PWResponse) -> None:
            req_url = response.request.url
            for record in reversed(captured_requests):
                if record.url == req_url and record.status_code is None:
                    record.status_code = response.status
                    try:
                        content_length = response.headers.get("content-length")
                        if content_length:
                            record.response_size_bytes = int(content_length)
                    except Exception:
                        pass
                    if req_url in request_timestamps:
                        record.timing_ms = (time.monotonic() - request_timestamps[req_url]) * 1000
                    break

        page.on("request", on_request)
        page.on("response", on_response)

        # ── Phase 1: Navigate ──
        _notify("loading", site.url)
        try:
            await page.goto(
                site.url,
                timeout=config.crawler.page_timeout_ms,
                wait_until="domcontentloaded",
            )
        except Exception as e:
            error_str = str(e)
            if "timeout" in error_str.lower() or "Timeout" in error_str:
                logger.warning("Timeout loading %s (%s)", site.url, mode.value)
                return CrawlResult(
                    site=site,
                    consent_mode=mode,
                    status=CrawlStatus.TIMEOUT,
                    started_at=started_at,
                    completed_at=now_iso(),
                    load_time_ms=config.crawler.page_timeout_ms,
                    requests=captured_requests,
                    error=error_str,
                )
            raise

        load_time_ms = int((time.monotonic() - start_time) * 1000)

        # Wait for async scripts to fire
        await asyncio.sleep(2)

        # ── Phase 2: Capture pre-consent state ──
        _notify("pre-consent")
        pre_consent_cookies: set[tuple[str, str]] = set()
        try:
            raw_cookies = await context.cookies()
            pre_consent_cookies = {(c["name"], c["domain"]) for c in raw_cookies}
        except Exception:
            pass

        pre_consent_request_count = len(captured_requests)

        # ── Phase 3: Handle cookie consent ──
        consent_info = ConsentInfo(banner_detected=False)
        if mode != ConsentMode.IGNORE:
            _notify("consent", mode.value)
            try:
                consent_info = await consent_handler.handle_consent(
                    page, mode, config.crawler.consent_timeout_ms
                )
            except Exception as e:
                logger.warning("Consent handling failed on %s: %s", site.url, e)
                consent_info = ConsentInfo(banner_detected=False)

            # ── Phase 4: Post-consent dwell (60s) ──
            if consent_info.action_taken:
                dwell_seconds = config.crawler.post_consent_wait_ms / 1000
                _notify("dwell", f"{int(dwell_seconds)}s post-consent")
                logger.info(
                    "Dwelling %ds post-consent on %s (%s)",
                    int(dwell_seconds), site.domain, mode.value,
                )

                # Dwell in chunks, logging new requests periodically
                chunk = 5  # check every 5s
                elapsed_dwell = 0.0
                while elapsed_dwell < dwell_seconds:
                    wait = min(chunk, dwell_seconds - elapsed_dwell)
                    await asyncio.sleep(wait)
                    elapsed_dwell += wait
                    new_req = len(captured_requests) - pre_consent_request_count
                    _notify("dwell", f"{int(elapsed_dwell)}/{int(dwell_seconds)}s — {new_req} new req")

                post_consent_request_count = len(captured_requests) - pre_consent_request_count
                logger.info(
                    "Post-consent dwell captured %d new requests on %s",
                    post_consent_request_count, site.domain,
                )

        # ── Phase 5: Scroll to trigger lazy-loaded trackers ──
        _notify("scrolling")
        try:
            for i in range(4):
                await page.evaluate("window.scrollBy(0, window.innerHeight / 2)")
                await asyncio.sleep(config.crawler.scroll_delay_ms / 1000)
        except Exception:
            pass

        # ── Phase 6: Final dwell ──
        final_dwell_s = config.crawler.final_dwell_ms / 1000
        if final_dwell_s > 0:
            _notify("final-wait", f"{int(final_dwell_s)}s")
            await asyncio.sleep(final_dwell_s)

        # ── Phase 7: Capture final state ──
        _notify("capturing")
        cookies = await _capture_cookies(
            context, tracker_db, pre_consent_cookies,
        )

        page_title = None
        final_url = None
        try:
            page_title = await page.title()
            final_url = page.url
        except Exception:
            pass

        # Screenshot
        screenshot_path = None
        if config.crawler.screenshot:
            try:
                ss_dir = config.resolve_path(config.output.screenshot_dir)
                ss_dir.mkdir(parents=True, exist_ok=True)
                ss_file = ss_dir / f"{site.domain}_{mode.value}.png"
                await page.screenshot(path=str(ss_file), full_page=False)
                screenshot_path = str(ss_file)
            except Exception as e:
                logger.warning("Screenshot failed for %s: %s", site.url, e)

        completed_at = now_iso()

        return CrawlResult(
            site=site,
            consent_mode=mode,
            status=CrawlStatus.SUCCESS,
            started_at=started_at,
            completed_at=completed_at,
            final_url=final_url,
            page_title=page_title,
            load_time_ms=load_time_ms,
            requests=captured_requests,
            cookies=cookies,
            consent_info=consent_info,
            screenshot_path=screenshot_path,
        )

    except Exception as e:
        logger.error("Error crawling %s (%s): %s", site.url, mode.value, e)
        return CrawlResult(
            site=site,
            consent_mode=mode,
            status=CrawlStatus.ERROR,
            started_at=started_at,
            completed_at=now_iso(),
            requests=captured_requests,
            error=str(e),
        )
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass


async def _capture_cookies(
    context,
    tracker_db: TrackerDatabase,
    pre_consent_cookies: set[tuple[str, str]],
) -> list[CookieRecord]:
    """Capture all cookies from the browser context."""
    cookies: list[CookieRecord] = []
    try:
        raw_cookies = await context.cookies()
        current_time = time.time()
        for c in raw_cookies:
            expires = c.get("expires", -1)
            is_session = expires <= 0
            expires_at = None
            lifetime_days = None
            if not is_session and expires > 0:
                expires_at = datetime.fromtimestamp(expires, tz=timezone.utc).isoformat()
                lifetime_days = (expires - current_time) / 86400

            cookie_domain = c.get("domain", "")
            was_before_consent = (c["name"], cookie_domain) in pre_consent_cookies
            entity, _ = tracker_db.classify(cookie_domain.lstrip("."))

            cookies.append(CookieRecord(
                name=c["name"],
                domain=cookie_domain,
                value_hash=hash_cookie_value(c.get("value", "")),
                path=c.get("path", "/"),
                expires_at=expires_at,
                lifetime_days=lifetime_days,
                is_secure=c.get("secure", False),
                is_http_only=c.get("httpOnly", False),
                same_site=c.get("sameSite", "None"),
                is_session=is_session,
                is_tracking_cookie=tracker_db.is_tracking_cookie(
                    c["name"], cookie_domain.lstrip(".")
                ),
                tracker_entity=entity,
                set_before_consent=was_before_consent,
                timestamp=now_iso(),
            ))
    except Exception as e:
        logger.warning("Failed to capture cookies: %s", e)

    return cookies
