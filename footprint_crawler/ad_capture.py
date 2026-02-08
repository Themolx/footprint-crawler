"""Individual ad screenshot capture module.

Captures each detected ad element as an individual PNG file, with JSON
sidecar metadata. Uses three capture strategies in order:
1. Frame element handle screenshot (for iframe ads — most reliable)
2. Playwright element.screenshot() via locator
3. Pillow crop fallback from viewport screenshot

Improvements from ad_creative_extractor.py:
- scroll_into_view_if_needed() before screenshot
- frame.wait_for_load_state() for iframe content to settle
- Direct frame_element() handle for iframe ads
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import Page

from .config import AdCaptureSettings
from .models import AdCapture, AdCaptureResult, AdElement

logger = logging.getLogger(__name__)


def _safe_filename(s: str) -> str:
    """Sanitize a string for use in filenames."""
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in s)


class AdCapturer:
    """Captures individual ad elements as PNG screenshots."""

    def __init__(self, config: AdCaptureSettings):
        self._config = config

    async def capture_ads(
        self,
        page: Page,
        ads: list[AdElement],
        run_id: str,
        domain: str,
        consent_mode: str,
    ) -> AdCaptureResult:
        """Screenshot individual ad elements and save with metadata."""
        if not self._config.enabled or not ads:
            return AdCaptureResult()

        base_dir = Path(self._config.output_dir) / run_id / _safe_filename(domain)
        base_dir.mkdir(parents=True, exist_ok=True)

        captures: list[AdCapture] = []
        limit = min(len(ads), self._config.max_captures)

        for i, ad in enumerate(ads[:limit]):
            capture = await self._capture_single(page, ad, i, base_dir, domain, consent_mode)
            captures.append(capture)

        total_captured = sum(1 for c in captures if c.capture_method != "failed")
        total_failed = sum(1 for c in captures if c.capture_method == "failed")

        logger.debug(
            "Ad capture: %d captured, %d failed for %s (%s)",
            total_captured, total_failed, domain, consent_mode,
        )

        return AdCaptureResult(
            captures=captures,
            total_captured=total_captured,
            total_failed=total_failed,
        )

    async def _capture_single(
        self,
        page: Page,
        ad: AdElement,
        index: int,
        base_dir: Path,
        domain: str,
        consent_mode: str,
    ) -> AdCapture:
        """Capture a single ad element as PNG + JSON metadata."""
        network = _safe_filename(ad.ad_network or "unknown")
        w, h = int(ad.width), int(ad.height)
        filename = f"{_safe_filename(domain)}__{consent_mode}__ad_{index:03d}__{network}__{w}x{h}"
        ss_path = str(base_dir / f"{filename}.png")
        meta_path = str(base_dir / f"{filename}.json")

        # Write JSON sidecar metadata
        metadata = {
            "source_site": domain,
            "consent_mode": consent_mode,
            "ad_network": ad.ad_network,
            "element_tag": ad.tag_name,
            "element_id": ad.ad_id,
            "element_classes": ad.ad_class,
            "iframe_src": ad.iframe_src,
            "position": {"x": ad.x, "y": ad.y},
            "size": {"width": w, "height": h},
            "iab_format": ad.iab_size,
            "is_above_fold": ad.y < 1080,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "screenshot_file": f"{filename}.png",
        }
        try:
            Path(meta_path).write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
        except Exception as e:
            logger.debug("Failed to write ad metadata: %s", e)

        # Strategy 1: Frame element handle (for iframe ads detected via frame scanning)
        if ad.is_iframe and ad.iframe_src:
            captured = await self._try_frame_element_screenshot(page, ad, ss_path)
            if captured:
                return AdCapture(
                    ad_index=index,
                    screenshot_path=ss_path,
                    metadata_path=meta_path,
                    width=w,
                    height=h,
                    capture_method="frame_element",
                )

        # Strategy 2: Element screenshot via locator
        captured = await self._try_element_screenshot(page, ad, ss_path)
        if captured:
            return AdCapture(
                ad_index=index,
                screenshot_path=ss_path,
                metadata_path=meta_path,
                width=w,
                height=h,
                capture_method="element",
            )

        # Strategy 3: Crop from viewport screenshot
        if self._config.crop_fallback:
            cropped = await self._try_crop_fallback(page, ad, ss_path)
            if cropped:
                return AdCapture(
                    ad_index=index,
                    screenshot_path=ss_path,
                    metadata_path=meta_path,
                    width=w,
                    height=h,
                    capture_method="crop_fallback",
                )

        return AdCapture(
            ad_index=index,
            screenshot_path=None,
            metadata_path=meta_path,
            width=w,
            height=h,
            capture_method="failed",
        )

    @staticmethod
    async def _try_frame_element_screenshot(page: Page, ad: AdElement, path: str) -> bool:
        """Capture iframe ad by finding its frame handle and screenshotting the element.

        This is the technique from ad_creative_extractor.py: iterate page.frames,
        match by URL, get frame_element(), scroll_into_view_if_needed(),
        wait for frame content to load, then screenshot.
        """
        try:
            iframe_src = ad.iframe_src or ""
            if not iframe_src:
                return False

            # Find matching frame by URL
            for frame in page.frames:
                try:
                    if frame.is_detached() or frame == page.main_frame:
                        continue

                    frame_url = frame.url or ""
                    # Match by containing the iframe src (or vice versa)
                    if not frame_url or (
                        iframe_src[:80].lower() not in frame_url.lower()
                        and frame_url[:80].lower() not in iframe_src.lower()
                    ):
                        continue

                    frame_element = await frame.frame_element()

                    # Scroll element into view (from ad_creative_extractor)
                    await frame_element.scroll_into_view_if_needed()

                    # Wait for iframe content to settle (from ad_creative_extractor)
                    try:
                        await frame.wait_for_load_state("domcontentloaded", timeout=2000)
                    except Exception:
                        pass

                    # Small stabilizing wait for rendering
                    await page.wait_for_timeout(500)

                    # Screenshot the frame element from the page context
                    await frame_element.screenshot(path=path, timeout=5000)
                    return True

                except Exception:
                    continue

        except Exception:
            pass

        return False

    @staticmethod
    async def _try_element_screenshot(page: Page, ad: AdElement, path: str) -> bool:
        """Try to screenshot the element directly via Playwright locator."""
        try:
            # Build a locator for the element
            if ad.ad_id:
                locator = page.locator(f"#{ad.ad_id}").first
            elif ad.is_iframe and ad.iframe_src:
                safe_src = ad.iframe_src[:80].replace("'", "\\'")
                locator = page.locator(f"iframe[src*='{safe_src}']").first
            else:
                locator = page.locator(ad.selector).first

            # Scroll into view before screenshotting (from ad_creative_extractor)
            try:
                await locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass

            # Small stabilizing wait
            await page.wait_for_timeout(300)

            await locator.screenshot(path=path, timeout=5000)
            return True
        except Exception:
            return False

    @staticmethod
    async def _try_crop_fallback(page: Page, ad: AdElement, path: str) -> bool:
        """Take a viewport screenshot and crop the ad region with Pillow."""
        try:
            from PIL import Image

            screenshot_bytes = await page.screenshot(type="png")
            img = Image.open(io.BytesIO(screenshot_bytes))

            x1 = max(0, int(ad.x))
            y1 = max(0, int(ad.y))
            x2 = min(img.width, int(ad.x + ad.width))
            y2 = min(img.height, int(ad.y + ad.height))

            if x2 <= x1 or y2 <= y1:
                return False

            cropped = img.crop((x1, y1, x2, y2))
            cropped.save(path, "PNG")
            return True
        except ImportError:
            logger.debug("Pillow not installed, crop fallback unavailable")
            return False
        except Exception:
            return False
