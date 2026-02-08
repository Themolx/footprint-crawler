"""Cookie consent banner detection and interaction.

Supports known CMPs (OneTrust, Cookiebot, CookieYes, Didomi, Quantcast)
and falls back to text-based button matching for custom implementations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from playwright.async_api import Frame, Page

from .config import ConsentPatterns
from .models import ConsentInfo, ConsentMode

logger = logging.getLogger(__name__)


@dataclass
class _CMPDefinition:
    """Definition of a known Consent Management Platform."""
    name: str
    detect_selector: str
    accept_selector: str | None
    reject_selector: str | None


# Known CMP definitions with their selectors
_CMP_DEFINITIONS: list[_CMPDefinition] = [
    _CMPDefinition(
        name="onetrust",
        detect_selector="#onetrust-banner-sdk",
        accept_selector="#onetrust-accept-btn-handler",
        reject_selector="#onetrust-reject-all-handler",
    ),
    _CMPDefinition(
        name="cookiebot",
        detect_selector="#CybotCookiebotDialog",
        accept_selector="#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
        reject_selector="#CybotCookiebotDialogBodyButtonDecline",
    ),
    _CMPDefinition(
        name="cookieyes",
        detect_selector=".cky-consent-container",
        accept_selector=".cky-btn-accept",
        reject_selector=".cky-btn-reject",
    ),
    _CMPDefinition(
        name="didomi",
        detect_selector="#didomi-popup",
        accept_selector="#didomi-notice-agree-button",
        reject_selector=".didomi-components-button--color.didomi-button-highlight.didomi-components-button--standard",
    ),
    _CMPDefinition(
        name="quantcast",
        detect_selector=".qc-cmp2-container",
        accept_selector=".qc-cmp2-summary-buttons button:first-child",
        reject_selector=".qc-cmp2-summary-buttons button:last-child",
    ),
    _CMPDefinition(
        name="termly",
        detect_selector="#termly-code-snippet-support",
        accept_selector="[data-tid='banner-accept']",
        reject_selector="[data-tid='banner-decline']",
    ),
    _CMPDefinition(
        name="osano",
        detect_selector=".osano-cm-window",
        accept_selector=".osano-cm-accept-all",
        reject_selector=".osano-cm-deny",
    ),
]


class ConsentHandler:
    """Handles detection and interaction with cookie consent banners."""

    def __init__(self, patterns: ConsentPatterns):
        self._accept_texts = [t.lower() for t in patterns.accept]
        self._reject_texts = [t.lower() for t in patterns.reject]

    async def handle_consent(
        self,
        page: Page,
        mode: ConsentMode,
        timeout_ms: int = 10000,
    ) -> ConsentInfo:
        """Detect and interact with a cookie consent banner.

        Args:
            page: The Playwright page to operate on.
            mode: ACCEPT or REJECT (IGNORE should not call this).
            timeout_ms: How long to wait for banner detection.

        Returns:
            ConsentInfo describing what was detected and what action was taken.
        """
        if mode == ConsentMode.IGNORE:
            return ConsentInfo(banner_detected=False)

        # Strategy 1: Try known CMPs
        for cmp in _CMP_DEFINITIONS:
            result = await self._try_cmp(page, cmp, mode, timeout_ms=2000)
            if result is not None:
                return result

        # Strategy 2: Check iframes for CMPs
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            for cmp in _CMP_DEFINITIONS:
                result = await self._try_cmp_in_frame(frame, cmp, mode)
                if result is not None:
                    return result

        # Strategy 3: Text-based button search on main page
        result = await self._try_text_match(page, mode, timeout_ms)
        if result is not None:
            return result

        # Strategy 4: Text-based search in iframes
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            result = await self._try_text_match_in_frame(frame, mode)
            if result is not None:
                return result

        # No banner detected
        logger.debug("No consent banner detected on %s", page.url)
        return ConsentInfo(banner_detected=False)

    async def _try_cmp(
        self,
        page: Page,
        cmp: _CMPDefinition,
        mode: ConsentMode,
        timeout_ms: int = 2000,
    ) -> ConsentInfo | None:
        """Try to detect and interact with a specific CMP."""
        try:
            banner = page.locator(cmp.detect_selector)
            if not await banner.count():
                return None
            if not await banner.first.is_visible(timeout=timeout_ms):
                return None
        except Exception:
            return None

        logger.info("Detected CMP: %s on %s", cmp.name, page.url)

        selector = cmp.accept_selector if mode == ConsentMode.ACCEPT else cmp.reject_selector
        if not selector:
            return ConsentInfo(
                banner_detected=True,
                cmp_platform=cmp.name,
                action_taken=False,
            )

        try:
            button = page.locator(selector)
            if await button.count() and await button.first.is_visible(timeout=1000):
                button_text = await button.first.inner_text()
                await button.first.click(timeout=3000)
                logger.info("Clicked %s button: %s", mode.value, button_text.strip())
                return ConsentInfo(
                    banner_detected=True,
                    cmp_platform=cmp.name,
                    button_text=button_text.strip(),
                    action_taken=True,
                )
        except Exception as e:
            logger.warning("Failed to click %s on %s: %s", cmp.name, page.url, e)

        return ConsentInfo(
            banner_detected=True,
            cmp_platform=cmp.name,
            action_taken=False,
        )

    async def _try_cmp_in_frame(
        self,
        frame: Frame,
        cmp: _CMPDefinition,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Try CMP detection within an iframe."""
        try:
            banner = frame.locator(cmp.detect_selector)
            if not await banner.count():
                return None
        except Exception:
            return None

        logger.info("Detected CMP in iframe: %s", cmp.name)

        selector = cmp.accept_selector if mode == ConsentMode.ACCEPT else cmp.reject_selector
        if not selector:
            return ConsentInfo(banner_detected=True, cmp_platform=cmp.name, action_taken=False)

        try:
            button = frame.locator(selector)
            if await button.count() and await button.first.is_visible(timeout=1000):
                button_text = await button.first.inner_text()
                await button.first.click(timeout=3000)
                return ConsentInfo(
                    banner_detected=True,
                    cmp_platform=cmp.name,
                    button_text=button_text.strip(),
                    action_taken=True,
                )
        except Exception as e:
            logger.warning("Failed to click CMP button in iframe: %s", e)

        return ConsentInfo(banner_detected=True, cmp_platform=cmp.name, action_taken=False)

    async def _try_text_match(
        self,
        page: Page,
        mode: ConsentMode,
        timeout_ms: int = 5000,
    ) -> ConsentInfo | None:
        """Search for consent buttons by text content."""
        texts = self._accept_texts if mode == ConsentMode.ACCEPT else self._reject_texts

        # Search clickable elements: buttons, links with role=button, divs with role=button
        selectors = [
            "button",
            "a[role='button']",
            "[role='button']",
            "input[type='submit']",
            "input[type='button']",
        ]

        for text_pattern in texts:
            # Skip overly generic patterns unless it's a last resort
            if text_pattern == "ok" and mode == ConsentMode.ACCEPT:
                continue  # handled below as last resort

            for selector_base in selectors:
                try:
                    # Use Playwright's text matching
                    elements = page.locator(f"{selector_base}:visible")
                    count = await elements.count()
                    for i in range(min(count, 30)):  # limit scan
                        try:
                            el = elements.nth(i)
                            el_text = (await el.inner_text(timeout=500)).strip().lower()
                            if text_pattern in el_text and len(el_text) < 60:
                                actual_text = (await el.inner_text(timeout=500)).strip()
                                await el.click(timeout=3000)
                                logger.info("Text match clicked: '%s' (pattern: '%s')", actual_text, text_pattern)
                                return ConsentInfo(
                                    banner_detected=True,
                                    cmp_platform="custom",
                                    button_text=actual_text,
                                    action_taken=True,
                                )
                        except Exception:
                            continue
                except Exception:
                    continue

        # Last resort for accept: try "OK" button (only if it's in a dialog-like container)
        if mode == ConsentMode.ACCEPT:
            try:
                ok_buttons = page.locator("button:visible, [role='button']:visible")
                count = await ok_buttons.count()
                for i in range(min(count, 20)):
                    try:
                        el = ok_buttons.nth(i)
                        el_text = (await el.inner_text(timeout=500)).strip()
                        if el_text.upper() == "OK":
                            # Check if it's likely a cookie banner (near words like cookie/souhlas)
                            parent_text = await el.evaluate(
                                "el => el.closest('div[class*=\"cookie\"], div[class*=\"consent\"], div[class*=\"banner\"], div[id*=\"cookie\"], div[id*=\"consent\"]')?.innerText || ''"
                            )
                            if parent_text:
                                await el.click(timeout=3000)
                                logger.info("OK button clicked in cookie context")
                                return ConsentInfo(
                                    banner_detected=True,
                                    cmp_platform="custom",
                                    button_text="OK",
                                    action_taken=True,
                                )
                    except Exception:
                        continue
            except Exception:
                pass

        return None

    async def _try_text_match_in_frame(
        self,
        frame: Frame,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Search for consent buttons by text content within an iframe."""
        texts = self._accept_texts if mode == ConsentMode.ACCEPT else self._reject_texts

        for text_pattern in texts:
            if text_pattern == "ok":
                continue
            try:
                elements = frame.locator("button:visible, [role='button']:visible")
                count = await elements.count()
                for i in range(min(count, 20)):
                    try:
                        el = elements.nth(i)
                        el_text = (await el.inner_text(timeout=500)).strip().lower()
                        if text_pattern in el_text and len(el_text) < 60:
                            actual_text = (await el.inner_text(timeout=500)).strip()
                            await el.click(timeout=3000)
                            logger.info("Text match in iframe: '%s'", actual_text)
                            return ConsentInfo(
                                banner_detected=True,
                                cmp_platform="custom_iframe",
                                button_text=actual_text,
                                action_taken=True,
                            )
                    except Exception:
                        continue
            except Exception:
                continue

        return None
