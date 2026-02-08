"""Cookie consent banner detection and interaction.

Multi-layer detection strategy:
1. Known CMP selectors (OneTrust, Cookiebot, CookieYes, Didomi, etc.)
2. CSS-based banner detection (fixed/sticky overlays with cookie-related classes/IDs)
3. Text-based button search (Czech + English patterns)
4. Iframe variants of all the above
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from playwright.async_api import Frame, Locator, Page

from .config import ConsentPatterns
from .models import ConsentInfo, ConsentMode

logger = logging.getLogger(__name__)


@dataclass
class _CMPDefinition:
    """Definition of a known Consent Management Platform."""
    name: str
    detect_selector: str
    accept_selectors: list[str]
    reject_selectors: list[str]


# Known CMP definitions — multiple fallback selectors per action
_CMP_DEFINITIONS: list[_CMPDefinition] = [
    _CMPDefinition(
        name="onetrust",
        detect_selector="#onetrust-banner-sdk",
        accept_selectors=[
            "#onetrust-accept-btn-handler",
            ".onetrust-close-btn-handler",
            "#accept-recommended-btn-handler",
        ],
        reject_selectors=[
            "#onetrust-reject-all-handler",
            ".ot-pc-refuse-all-handler",
            "#onetrust-pc-btn-handler",  # opens settings (fallback)
        ],
    ),
    _CMPDefinition(
        name="cookiebot",
        detect_selector="#CybotCookiebotDialog",
        accept_selectors=[
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "#CybotCookiebotDialogBodyButtonAccept",
            "#CybotCookiebotDialogBodyLevelButtonAccept",
            "a[data-cb-accept]",
        ],
        reject_selectors=[
            "#CybotCookiebotDialogBodyButtonDecline",
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll",
            "a[data-cb-decline]",
        ],
    ),
    _CMPDefinition(
        name="cookieyes",
        detect_selector=".cky-consent-container",
        accept_selectors=[".cky-btn-accept"],
        reject_selectors=[".cky-btn-reject", ".cky-btn-customize"],
    ),
    _CMPDefinition(
        name="didomi",
        detect_selector="#didomi-popup, #didomi-notice",
        accept_selectors=[
            "#didomi-notice-agree-button",
            "[data-testid='notice-accept-btn']",
            ".didomi-components-button--color.didomi-button-highlight",
        ],
        reject_selectors=[
            "#didomi-notice-disagree-button",
            "[data-testid='notice-disagree-btn']",
            ".didomi-components-button:not(.didomi-button-highlight)",
        ],
    ),
    _CMPDefinition(
        name="quantcast",
        detect_selector=".qc-cmp2-container, .qc-cmp-ui-container",
        accept_selectors=[
            "[data-testid='GDPR-CTA-accept']",
            ".qc-cmp2-summary-buttons button:first-child",
            ".qc-cmp-button[mode='primary']",
        ],
        reject_selectors=[
            "[data-testid='GDPR-CTA-refuse']",
            ".qc-cmp2-summary-buttons button:last-child",
            ".qc-cmp-button[mode='secondary']",
        ],
    ),
    _CMPDefinition(
        name="termly",
        detect_selector="#termly-code-snippet-support",
        accept_selectors=["[data-tid='banner-accept']"],
        reject_selectors=["[data-tid='banner-decline']"],
    ),
    _CMPDefinition(
        name="osano",
        detect_selector=".osano-cm-window",
        accept_selectors=[".osano-cm-accept-all", ".osano-cm-accept"],
        reject_selectors=[".osano-cm-deny", ".osano-cm-denyAll"],
    ),
    _CMPDefinition(
        name="trustarc",
        detect_selector="#truste-consent-track, .truste_box_overlay, #consent_blackbar",
        accept_selectors=[
            "#truste-consent-button",
            ".truste-consent-button",
            ".call[data-accept]",
        ],
        reject_selectors=[
            "#truste-consent-required",
            ".truste-consent-required",
        ],
    ),
    _CMPDefinition(
        name="iubenda",
        detect_selector=".iubenda-cs-container, #iubenda-cs-banner",
        accept_selectors=[
            ".iubenda-cs-accept-btn",
            "#iubenda-cs-accept-btn",
        ],
        reject_selectors=[
            ".iubenda-cs-reject-btn",
            "#iubenda-cs-reject-btn",
        ],
    ),
    _CMPDefinition(
        name="klaro",
        detect_selector=".klaro .cookie-notice, .klaro .cookie-modal",
        accept_selectors=[
            ".klaro .cm-btn-accept-all",
            ".klaro .cm-btn-accept",
        ],
        reject_selectors=[
            ".klaro .cm-btn-decline",
            ".klaro .cm-btn-deny",
        ],
    ),
    _CMPDefinition(
        name="complianz",
        detect_selector=".cmplz-cookiebanner, #cmplz-cookiebanner-container",
        accept_selectors=[
            ".cmplz-btn.cmplz-accept",
            ".cmplz-accept-all",
        ],
        reject_selectors=[
            ".cmplz-btn.cmplz-deny",
            ".cmplz-deny",
        ],
    ),
    _CMPDefinition(
        name="cookie_notice",
        detect_selector="#cookie-notice, .cookie-notice-container",
        accept_selectors=[
            "#cn-accept-cookie",
            ".cn-set-cookie",
            "#cookie-notice .cn-button",
        ],
        reject_selectors=[
            "#cn-refuse-cookie",
            ".cn-decline-cookie",
        ],
    ),
    _CMPDefinition(
        name="civic_uk",
        detect_selector="#ccc, .ccc-notify",
        accept_selectors=[
            "#ccc-recommended-settings",
            ".ccc-accept-button",
        ],
        reject_selectors=[
            "#ccc-reject-settings",
            ".ccc-reject-button",
        ],
    ),
    _CMPDefinition(
        name="sourcepoint",
        detect_selector="[id^='sp_message_container']",
        accept_selectors=[
            "button[title='Accept']",
            "button[title='Accept All']",
            "button[title='OK']",
        ],
        reject_selectors=[
            "button[title='Reject']",
            "button[title='Reject All']",
        ],
    ),
]

# CSS patterns to detect generic cookie banners by class/ID naming
_BANNER_CSS_SELECTORS: list[str] = [
    # ID-based
    "[id*='cookie-bar']",
    "[id*='cookie-banner']",
    "[id*='cookie-consent']",
    "[id*='cookie-notice']",
    "[id*='cookie-popup']",
    "[id*='cookie-modal']",
    "[id*='cookie-dialog']",
    "[id*='cookie-layer']",
    "[id*='cookie-wall']",
    "[id*='cookiebar']",
    "[id*='cookiebanner']",
    "[id*='cookieconsent']",
    "[id*='cookienotice']",
    "[id*='consent-banner']",
    "[id*='consent-bar']",
    "[id*='consent-popup']",
    "[id*='consent-modal']",
    "[id*='consent-dialog']",
    "[id*='gdpr-banner']",
    "[id*='gdpr-consent']",
    "[id*='gdpr-popup']",
    "[id*='gdpr']",
    "[id*='privacy-bar']",
    "[id*='privacy-banner']",
    # Class-based
    "[class*='cookie-bar']",
    "[class*='cookie-banner']",
    "[class*='cookie-consent']",
    "[class*='cookie-notice']",
    "[class*='cookie-popup']",
    "[class*='cookie-modal']",
    "[class*='cookie-wall']",
    "[class*='cookiebar']",
    "[class*='cookiebanner']",
    "[class*='cookieconsent']",
    "[class*='consent-banner']",
    "[class*='consent-bar']",
    "[class*='consent-popup']",
    "[class*='consent-modal']",
    "[class*='gdpr-banner']",
    "[class*='gdpr-consent']",
    "[class*='gdpr-popup']",
    "[class*='privacy-bar']",
    "[class*='privacy-banner']",
    "[class*='cc-window']",
    "[class*='cc-banner']",
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
        timeout_ms: int = 15000,
    ) -> ConsentInfo:
        """Detect and interact with a cookie consent banner."""
        if mode == ConsentMode.IGNORE:
            return ConsentInfo(banner_detected=False)

        # Wait a bit for banners to appear (many load with a delay)
        await asyncio.sleep(2)

        # Strategy 1: Known CMPs on main page
        for cmp in _CMP_DEFINITIONS:
            result = await self._try_cmp(page, cmp, mode)
            if result is not None:
                return result

        # Strategy 2: Known CMPs in iframes
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            for cmp in _CMP_DEFINITIONS:
                result = await self._try_cmp_in_frame(frame, cmp, mode)
                if result is not None:
                    return result

        # Strategy 3: CSS-based generic banner detection + text match inside it
        result = await self._try_css_banner(page, mode)
        if result is not None:
            return result

        # Strategy 4: Full-page text-based button search
        result = await self._try_text_match(page, mode)
        if result is not None:
            return result

        # Strategy 5: Text-based search in iframes
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            result = await self._try_text_match_in_frame(frame, mode)
            if result is not None:
                return result

        # Strategy 6: Sourcepoint and similar CMPs that use nested iframes
        result = await self._try_nested_iframe_cmp(page, mode)
        if result is not None:
            return result

        logger.debug("No consent banner detected on %s", page.url)
        return ConsentInfo(banner_detected=False)

    async def _try_cmp(
        self,
        page: Page,
        cmp: _CMPDefinition,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Try to detect and interact with a specific CMP."""
        try:
            banner = page.locator(cmp.detect_selector)
            if not await banner.count():
                return None
            if not await banner.first.is_visible(timeout=1500):
                return None
        except Exception:
            return None

        logger.info("Detected CMP: %s on %s", cmp.name, page.url)

        selectors = cmp.accept_selectors if mode == ConsentMode.ACCEPT else cmp.reject_selectors
        return await self._click_first_visible(page, selectors, cmp.name)

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
        selectors = cmp.accept_selectors if mode == ConsentMode.ACCEPT else cmp.reject_selectors

        for selector in selectors:
            try:
                button = frame.locator(selector)
                if await button.count() and await button.first.is_visible(timeout=1000):
                    button_text = (await button.first.inner_text(timeout=500)).strip()
                    await button.first.click(timeout=3000)
                    return ConsentInfo(
                        banner_detected=True,
                        cmp_platform=cmp.name,
                        button_text=button_text,
                        action_taken=True,
                    )
            except Exception:
                continue

        return ConsentInfo(banner_detected=True, cmp_platform=cmp.name, action_taken=False)

    async def _click_first_visible(
        self,
        page: Page,
        selectors: list[str],
        cmp_name: str,
    ) -> ConsentInfo:
        """Try clicking the first visible element from a list of selectors."""
        for selector in selectors:
            try:
                button = page.locator(selector)
                if await button.count() and await button.first.is_visible(timeout=1000):
                    button_text = (await button.first.inner_text(timeout=500)).strip()
                    await button.first.click(timeout=3000)
                    logger.info("Clicked CMP button: '%s' (%s)", button_text, cmp_name)
                    return ConsentInfo(
                        banner_detected=True,
                        cmp_platform=cmp_name,
                        button_text=button_text,
                        action_taken=True,
                    )
            except Exception:
                continue

        return ConsentInfo(banner_detected=True, cmp_platform=cmp_name, action_taken=False)

    async def _try_css_banner(
        self,
        page: Page,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Detect banner by CSS class/ID patterns, then search for buttons inside."""
        for css_sel in _BANNER_CSS_SELECTORS:
            try:
                banner = page.locator(f"{css_sel}:visible")
                if not await banner.count():
                    continue

                # Found a visible banner-like element — search for buttons inside
                container = banner.first
                texts = self._accept_texts if mode == ConsentMode.ACCEPT else self._reject_texts
                result = await self._find_button_in_container(container, texts, "css_banner")
                if result is not None:
                    return result
            except Exception:
                continue

        return None

    async def _find_button_in_container(
        self,
        container: Locator,
        text_patterns: list[str],
        cmp_label: str,
    ) -> ConsentInfo | None:
        """Find and click a matching button within a container element."""
        try:
            buttons = container.locator("button, a, [role='button'], input[type='submit'], input[type='button'], span[onclick], div[onclick]")
            count = await buttons.count()

            for text_pattern in text_patterns:
                if text_pattern == "ok":
                    continue  # too generic, skip unless last resort
                for i in range(min(count, 30)):
                    try:
                        el = buttons.nth(i)
                        if not await el.is_visible(timeout=300):
                            continue
                        el_text = (await el.inner_text(timeout=500)).strip()
                        if text_pattern in el_text.lower() and len(el_text) < 80:
                            await el.click(timeout=3000)
                            logger.info("CSS banner button clicked: '%s' (pattern: '%s')", el_text, text_pattern)
                            return ConsentInfo(
                                banner_detected=True,
                                cmp_platform=cmp_label,
                                button_text=el_text,
                                action_taken=True,
                            )
                    except Exception:
                        continue
        except Exception:
            pass

        return None

    async def _try_text_match(
        self,
        page: Page,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Search the entire page for consent buttons by text content."""
        texts = self._accept_texts if mode == ConsentMode.ACCEPT else self._reject_texts

        # Broad set of clickable element selectors
        selectors = "button:visible, a:visible, [role='button']:visible, input[type='submit']:visible, input[type='button']:visible"

        for text_pattern in texts:
            if text_pattern == "ok":
                continue

            try:
                elements = page.locator(selectors)
                count = await elements.count()
                for i in range(min(count, 50)):
                    try:
                        el = elements.nth(i)
                        el_text = (await el.inner_text(timeout=300)).strip()
                        el_lower = el_text.lower()

                        if text_pattern not in el_lower:
                            continue
                        if len(el_text) > 80:
                            continue

                        # Verify this button is likely in a consent context
                        is_consent = await self._is_consent_context(el)
                        if not is_consent and len(el_text) < 4:
                            continue  # skip short generic matches outside consent context

                        await el.click(timeout=3000)
                        logger.info("Text match clicked: '%s' (pattern: '%s')", el_text, text_pattern)
                        return ConsentInfo(
                            banner_detected=True,
                            cmp_platform="text_match",
                            button_text=el_text,
                            action_taken=True,
                        )
                    except Exception:
                        continue
            except Exception:
                continue

        # Last resort for accept: try "OK" in a consent context
        if mode == ConsentMode.ACCEPT:
            result = await self._try_ok_button(page)
            if result is not None:
                return result

        return None

    async def _is_consent_context(self, el: Locator) -> bool:
        """Check if an element sits inside a consent/cookie-related container."""
        try:
            result = await el.evaluate("""el => {
                const keywords = ['cookie', 'consent', 'gdpr', 'privacy', 'souhlas', 'soukrom'];
                let node = el.parentElement;
                for (let i = 0; i < 8 && node; i++) {
                    const cls = (node.className || '').toLowerCase();
                    const id = (node.id || '').toLowerCase();
                    const role = (node.getAttribute('role') || '').toLowerCase();
                    for (const kw of keywords) {
                        if (cls.includes(kw) || id.includes(kw)) return true;
                    }
                    if (role === 'dialog' || role === 'alertdialog') return true;
                    node = node.parentElement;
                }
                return false;
            }""")
            return bool(result)
        except Exception:
            return False

    async def _try_ok_button(self, page: Page) -> ConsentInfo | None:
        """Last resort: find an 'OK' button inside a consent-like container."""
        try:
            buttons = page.locator("button:visible, [role='button']:visible")
            count = await buttons.count()
            for i in range(min(count, 30)):
                try:
                    el = buttons.nth(i)
                    el_text = (await el.inner_text(timeout=300)).strip()
                    if el_text.upper() != "OK":
                        continue
                    if await self._is_consent_context(el):
                        await el.click(timeout=3000)
                        logger.info("OK button clicked in consent context")
                        return ConsentInfo(
                            banner_detected=True,
                            cmp_platform="ok_fallback",
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
                elements = frame.locator("button:visible, a:visible, [role='button']:visible")
                count = await elements.count()
                for i in range(min(count, 30)):
                    try:
                        el = elements.nth(i)
                        el_text = (await el.inner_text(timeout=300)).strip()
                        if text_pattern in el_text.lower() and len(el_text) < 80:
                            await el.click(timeout=3000)
                            logger.info("Text match in iframe: '%s'", el_text)
                            return ConsentInfo(
                                banner_detected=True,
                                cmp_platform="iframe_text",
                                button_text=el_text,
                                action_taken=True,
                            )
                    except Exception:
                        continue
            except Exception:
                continue

        return None

    async def _try_nested_iframe_cmp(
        self,
        page: Page,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Handle CMPs that render inside nested iframes (e.g., Sourcepoint)."""
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                frame_url = frame.url or ""
                # Sourcepoint, some OneTrust variants, TCF iframes
                if any(kw in frame_url.lower() for kw in [
                    "consent", "cookie", "gdpr", "privacy", "cmp", "sp_message",
                    "sourcepoint", "quantcast",
                ]):
                    texts = self._accept_texts if mode == ConsentMode.ACCEPT else self._reject_texts
                    elements = frame.locator("button:visible, a:visible, [role='button']:visible")
                    count = await elements.count()
                    for text_pattern in texts:
                        if text_pattern == "ok":
                            continue
                        for i in range(min(count, 20)):
                            try:
                                el = elements.nth(i)
                                el_text = (await el.inner_text(timeout=300)).strip()
                                if text_pattern in el_text.lower() and len(el_text) < 80:
                                    await el.click(timeout=3000)
                                    logger.info("Nested iframe CMP: '%s' in %s", el_text, frame_url[:60])
                                    return ConsentInfo(
                                        banner_detected=True,
                                        cmp_platform="iframe_cmp",
                                        button_text=el_text,
                                        action_taken=True,
                                    )
                            except Exception:
                                continue
            except Exception:
                continue

        return None
