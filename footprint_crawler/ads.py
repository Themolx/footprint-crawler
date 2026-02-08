"""Ad element detection and measurement module.

Scans the DOM for advertising elements using two complementary approaches:
1. CSS selector-based DOM scanning (existing approach)
2. Frame-based ad detection — iterates page.frames to find ad iframes by
   domain, size, and visibility (from ad_creative_extractor)

Measures dimensions, matches against IAB standard sizes, and computes ad
density (percentage of viewport occupied by ads).
"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from .config import AdsSettings
from .models import AdDetectionResult, AdElement

logger = logging.getLogger(__name__)

# CSS selectors that match known ad patterns
AD_SELECTORS = [
    # Google Ads
    "ins.adsbygoogle",
    "[id^='google_ads_']",
    "[id^='div-gpt-ad']",
    "div[data-google-query-id]",
    "div[data-ad-slot]",
    "iframe[id^='google_ads_iframe']",
    "iframe[src*='doubleclick.net']",
    "iframe[src*='googlesyndication']",
    # Generic ad containers (ID patterns)
    "[id*='ad-container']", "[id*='ad-wrapper']", "[id*='ad-slot']",
    "[id*='ad_container']", "[id*='ad_wrapper']", "[id*='ad_slot']",
    "[id*='advert']", "[id*='banner-ad']", "[id*='sponsor']",
    "[id*='adsense']", "[id*='adform']", "[id*='dfp']",
    # Generic ad containers (class patterns)
    "[class*='ad-container']", "[class*='ad-wrapper']", "[class*='ad-slot']",
    "[class*='ad-unit']", "[class*='advert']", "[class*='banner-ad']",
    "[class*='sponsored']", "[class*='commercial']",
    # Czech-specific
    "[class*='reklama']", "[class*='inzerce']",
    "[id*='sklik']",
    "iframe[src*='sklik']",
    "iframe[src*='r2b2']",
    "iframe[src*='imedia']",
    "iframe[src*='sssp.cz']",
    "iframe[src*='ad.seznam.cz']",
    # Data attribute patterns
    "[data-ad]", "[data-ad-slot]", "[data-ad-unit]",
    "[data-advertisement]", "[data-sponsor]", "[data-adservice]",
    # IAB / header bidding
    "[id^='pb-slot']",
    "[class*='prebid']",
    # Other ad networks
    "iframe[src*='adform']",
    "iframe[src*='amazon-adsystem']",
    "iframe[src*='criteo']",
    "iframe[src*='taboola']",
    "iframe[src*='outbrain']",
    # Generic iframe ad patterns
    "iframe[src*='/ads/']",
    "iframe[src*='adserver']",
]

# IAB standard ad sizes: (width, height, name)
IAB_STANDARD_SIZES = [
    (728, 90, "leaderboard"),
    (300, 250, "medium_rectangle"),
    (160, 600, "wide_skyscraper"),
    (120, 600, "skyscraper"),
    (300, 600, "half_page"),
    (320, 50, "mobile_leaderboard"),
    (320, 100, "large_mobile_banner"),
    (970, 250, "billboard"),
    (970, 90, "large_leaderboard"),
    (300, 50, "mobile_banner"),
    (468, 60, "full_banner"),
    (234, 60, "half_banner"),
    (336, 280, "large_rectangle"),
    (250, 250, "square"),
    (180, 150, "rectangle"),
    (300, 1050, "portrait"),
    (580, 400, "netboard"),
    (480, 120, "superboard"),
]

# Ad network detection patterns for iframe src
_AD_NETWORK_PATTERNS = {
    "googlesyndication": "Google",
    "doubleclick": "Google",
    "googleadservices": "Google",
    "google_ads": "Google",
    "adform": "Adform",
    "sklik": "Seznam.cz",
    "ad.seznam": "Seznam.cz",
    "sssp.cz": "Seznam.cz",
    "imedia": "Seznam.cz",
    "r2b2": "R2B2",
    "criteo": "Criteo",
    "amazon-adsystem": "Amazon",
    "taboola": "Taboola",
    "outbrain": "Outbrain",
    "facebook.com/plugins/ad": "Meta",
}

# Known ad domains for frame-based detection (from ad_creative_extractor)
_AD_FRAME_DOMAINS = frozenset({
    "googlesyndication",
    "doubleclick",
    "appnexus",
    "rubiconproject",
    "criteo",
    "adform",
    "amazon-adsystem",
    "taboola",
    "outbrain",
    "sklik",
    "sssp.cz",
    "r2b2",
    "imedia",
    "ad.seznam",
    "adnxs",
    "pubmatic",
    "openx",
    "smartadserver",
    "casalemedia",
    "indexexchange",
    "33across",
    "yieldmo",
    "sharethrough",
})

# JavaScript that scans the DOM for ad elements.
# The selector list is embedded as a JSON array.
_AD_DETECTION_JS = """
() => {
    const SELECTORS = """ + str(AD_SELECTORS).replace("'", '"') + """;
    const seen = new Set();
    const results = [];

    function getUniqueKey(el) {
        const rect = el.getBoundingClientRect();
        return Math.round(rect.x) + ',' + Math.round(rect.y) + ',' +
               Math.round(rect.width) + ',' + Math.round(rect.height);
    }

    function isVisible(el) {
        if (!el.offsetParent && el.tagName !== 'BODY' && el.tagName !== 'HTML') {
            const style = window.getComputedStyle(el);
            if (style.position !== 'fixed' && style.position !== 'sticky') return false;
        }
        const style = window.getComputedStyle(el);
        if (style.display === 'none') return false;
        if (style.visibility === 'hidden') return false;
        if (parseFloat(style.opacity) < 0.1) return false;
        return true;
    }

    for (const selector of SELECTORS) {
        try {
            const elements = document.querySelectorAll(selector);
            for (const el of elements) {
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;

                const key = getUniqueKey(el);
                if (seen.has(key)) continue;
                seen.add(key);

                const visible = isVisible(el);
                const tagName = el.tagName.toLowerCase();
                let iframeSrc = null;
                if (tagName === 'iframe') {
                    try { iframeSrc = el.src || el.getAttribute('src'); } catch(e) {}
                }

                results.push({
                    selector: selector,
                    tagName: tagName,
                    id: el.id || null,
                    className: (el.className && typeof el.className === 'string')
                               ? el.className.substring(0, 200) : null,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    visible: visible,
                    iframeSrc: iframeSrc
                });
            }
        } catch(e) {}
    }

    return results;
}
"""


class AdDetector:
    """Detects and measures ad elements in the page DOM."""

    def __init__(self, config: AdsSettings):
        self._config = config
        self._tolerance = config.iab_tolerance_pct / 100.0

    async def detect_ads(self, page: Page) -> AdDetectionResult:
        """Scan the DOM for ad elements using CSS selectors + frame scanning.

        Call after page load + dwell. Combines two detection approaches:
        1. CSS selector-based DOM scanning (main page)
        2. Frame-based ad detection (iterates page.frames for ad iframes)
        """
        if not self._config.enabled:
            return AdDetectionResult()

        # Phase 1: CSS selector-based detection
        try:
            raw_ads = await page.evaluate(_AD_DETECTION_JS)
        except Exception as e:
            logger.debug("Ad detection JS failed: %s", e)
            raw_ads = []

        # Phase 2: Frame-based ad detection
        frame_ads = await self._detect_frame_ads(page)

        try:
            viewport = await page.evaluate(
                "() => ({ w: window.innerWidth, h: window.innerHeight })"
            )
            viewport_area = viewport["w"] * viewport["h"]
        except Exception:
            viewport_area = 1920 * 1080

        ads: list[AdElement] = []
        total_area = 0
        seen_keys: set[str] = set()

        # Process CSS selector results
        for raw in raw_ads:
            w = raw.get("width", 0)
            h = raw.get("height", 0)

            if w < self._config.min_width or h < self._config.min_height:
                continue

            # Dedup key based on position + size
            key = f"{raw.get('x', 0)},{raw.get('y', 0)},{w},{h}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            is_visible = raw.get("visible", True)
            iframe_src = raw.get("iframeSrc")
            tag_name = raw.get("tagName", "")
            is_iframe = tag_name == "iframe"
            ad_network = self._detect_ad_network(
                iframe_src, raw.get("id"), raw.get("className"),
            )
            iab_size = self._match_iab_size(w, h)

            ad = AdElement(
                selector=raw.get("selector", ""),
                tag_name=tag_name,
                ad_id=raw.get("id"),
                ad_class=raw.get("className"),
                x=raw.get("x", 0),
                y=raw.get("y", 0),
                width=w,
                height=h,
                is_visible=is_visible,
                is_iframe=is_iframe,
                iframe_src=iframe_src,
                iab_size=iab_size,
                ad_network=ad_network,
            )
            ads.append(ad)
            if is_visible:
                total_area += w * h

        # Process frame-based results (deduplicating against CSS results)
        for frame_ad in frame_ads:
            key = f"{frame_ad.x},{frame_ad.y},{frame_ad.width},{frame_ad.height}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            ads.append(frame_ad)
            if frame_ad.is_visible:
                total_area += frame_ad.width * frame_ad.height

        visible_count = sum(1 for a in ads if a.is_visible)
        density = (total_area / viewport_area) if viewport_area > 0 else 0.0
        iab_count = sum(1 for a in ads if a.iab_size is not None)

        result = AdDetectionResult(
            ads=ads,
            total_ad_count=len(ads),
            visible_ad_count=visible_count,
            ad_density=round(density, 4),
            total_ad_area_px=total_area,
            iab_standard_count=iab_count,
        )

        logger.debug(
            "Detected %d ads (%d visible, %d from frames, density=%.1f%%, %d IAB standard)",
            len(ads), visible_count, len(frame_ads), density * 100, iab_count,
        )
        return result

    async def _detect_frame_ads(self, page: Page) -> list[AdElement]:
        """Detect ads by iterating over page.frames.

        Inspired by ad_creative_extractor.py: checks each iframe's URL
        against known ad domains, filters by size and visibility, and
        extracts bounding box via frame_element().
        """
        frame_ads: list[AdElement] = []

        for frame in page.frames:
            try:
                if frame.is_detached() or frame == page.main_frame:
                    continue

                frame_url = frame.url or ""
                if not frame_url or frame_url == "about:blank":
                    continue

                # Check if this frame URL matches a known ad domain
                frame_url_lower = frame_url.lower()
                is_ad_domain = any(d in frame_url_lower for d in _AD_FRAME_DOMAINS)

                # Get frame element handle and bounding box
                frame_element = await frame.frame_element()
                box = await frame_element.bounding_box()

                if not box:
                    continue

                w = int(box["width"])
                h = int(box["height"])

                if w < self._config.min_width or h < self._config.min_height:
                    continue

                # Check visibility
                try:
                    visible = await frame_element.is_visible()
                except Exception:
                    visible = True

                # Accept if it's a known ad domain OR it's a large visible iframe
                # matching an IAB standard size (strong ad signal)
                is_iab = self._match_iab_size(w, h) is not None
                if not is_ad_domain and not is_iab:
                    continue

                ad_network = self._detect_ad_network(frame_url, None, None)
                iab_size = self._match_iab_size(w, h)

                ad = AdElement(
                    selector=f"frame:{frame_url[:100]}",
                    tag_name="iframe",
                    ad_id=None,
                    ad_class=None,
                    x=int(box["x"]),
                    y=int(box["y"]),
                    width=w,
                    height=h,
                    is_visible=visible,
                    is_iframe=True,
                    iframe_src=frame_url[:500],
                    iab_size=iab_size,
                    ad_network=ad_network,
                )
                frame_ads.append(ad)

            except Exception:
                # Frames can detach at any time
                continue

        return frame_ads

    def _match_iab_size(self, w: int, h: int) -> str | None:
        """Check if dimensions match an IAB standard size within tolerance."""
        if w <= 0 or h <= 0:
            return None
        for std_w, std_h, _name in IAB_STANDARD_SIZES:
            if (abs(w - std_w) / std_w <= self._tolerance and
                    abs(h - std_h) / std_h <= self._tolerance):
                return f"{std_w}x{std_h}"
        return None

    @staticmethod
    def _detect_ad_network(
        iframe_src: str | None,
        element_id: str | None,
        element_class: str | None,
    ) -> str | None:
        """Try to identify the ad network from element attributes."""
        sources = []
        if iframe_src:
            sources.append(iframe_src.lower())
        if element_id:
            sources.append(element_id.lower())
        if element_class:
            sources.append(element_class.lower())

        combined = " ".join(sources)
        for pattern, network in _AD_NETWORK_PATTERNS.items():
            if pattern in combined:
                return network
        return None
