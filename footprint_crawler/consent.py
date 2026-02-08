"""Cookie consent banner detection and interaction.

Multi-layer detection strategy (10 strategies, ordered by reliability):
1. Known CMP selectors (OneTrust, Cookiebot, CookieYes, Didomi, etc.)
2. Czech-specific CMP definitions (Seznam, Alza, iDNES, Mall/CZC)
3. Shadow DOM banner piercing (szn-cwl, didomi-host, etc.)
4. Known CMPs in iframes
5. Two-step consent flows (settings page then accept/reject)
6. Playwright get_by_text (pierces some Shadow DOM boundaries)
7. Playwright get_by_role (accessibility-based)
8. CSS-based banner detection + text match inside
9. Full-page text-based button search
10. Nested iframe CMPs (Sourcepoint, etc.)

Fallbacks:
- Didomi JS API (window.Didomi.setUserAgreeToAll)
- OK button in consent context
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


# ─── Known CMP definitions — multiple fallback selectors per action ──────────
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
            "#onetrust-pc-btn-handler",
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

# ─── Czech-specific CMP definitions ──────────────────────────────────────────
_CZECH_CMP_DEFINITIONS: list[_CMPDefinition] = [
    _CMPDefinition(
        name="alza",
        detect_selector="div.js-cookies-info, .cookies-info",
        accept_selectors=[
            "a.js-cookies-info-accept",
            ".js-cookies-info-accept",
        ],
        reject_selectors=[
            "a.js-cookies-info-reject",
            ".js-cookies-info-reject",
        ],
    ),
    _CMPDefinition(
        name="idnes_content_wall",
        detect_selector="#content-wall, .content-wall, .cookie-info",
        accept_selectors=[
            ".btn-cons.contentwall_ok",
            ".contentwall_ok",
            "button.accept-cookies",
        ],
        reject_selectors=[
            ".btn-cons.contentwall_reject",
            "button.reject-cookies",
        ],
    ),
    _CMPDefinition(
        name="allegro_group",
        detect_selector="[data-testid='cookie-consent-dialog'], [data-testid='consent-popup']",
        accept_selectors=[
            "button[data-testid='accept_home_view_action']",
            "button[data-testid='consent-accept-all']",
        ],
        reject_selectors=[
            "button[data-testid='reject_home_view_action']",
            "button[data-testid='consent-reject-all']",
        ],
    ),
    _CMPDefinition(
        name="cpex",
        detect_selector="#cpexSubs, [id^='cpexSubs']",
        accept_selectors=[
            "#cpexSubs_consentButton",
            "button[id*='consent']",
        ],
        reject_selectors=[
            "#cpexSubs_rejectButton",
            "button[id*='reject']",
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

# Shadow DOM host elements known to contain consent banners
_SHADOW_DOM_HOSTS: list[str] = [
    "szn-cwl",
    "#didomi-host",
    "cookie-consent-widget",
    "[data-consent-shadow]",
    "consent-manager",
    "cookie-banner",
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
        """Detect and interact with a cookie consent banner.

        Tries 10 strategies in order of reliability, returning as soon as
        one succeeds.
        """
        if mode == ConsentMode.IGNORE:
            return ConsentInfo(banner_detected=False)

        # Wait a bit for banners to appear (many load with a delay)
        await asyncio.sleep(2)

        # Strategy 1: Known CMPs on main page
        for cmp in _CMP_DEFINITIONS:
            result = await self._try_cmp(page, cmp, mode)
            if result is not None:
                return result

        # Strategy 2: Czech-specific CMP definitions
        for cmp in _CZECH_CMP_DEFINITIONS:
            result = await self._try_cmp(page, cmp, mode)
            if result is not None:
                return result

        # Strategy 3: Shadow DOM banners (szn-cwl, didomi-host, etc.)
        result = await self._try_shadow_dom_banner(page, mode)
        if result is not None:
            return result

        # Strategy 4: Known CMPs in iframes
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            for cmp in _CMP_DEFINITIONS + _CZECH_CMP_DEFINITIONS:
                result = await self._try_cmp_in_frame(frame, cmp, mode)
                if result is not None:
                    return result

        # Strategy 5: Two-step consent flows (Seznam redirect, etc.)
        result = await self._try_two_step_consent(page, mode)
        if result is not None:
            return result

        # Strategy 6: Playwright get_by_text (pierces some Shadow DOM)
        result = await self._try_get_by_text(page, mode)
        if result is not None:
            return result

        # Strategy 7: Playwright get_by_role
        result = await self._try_get_by_role(page, mode)
        if result is not None:
            return result

        # Strategy 8: CSS-based generic banner detection + text match inside
        result = await self._try_css_banner(page, mode)
        if result is not None:
            return result

        # Strategy 9: Full-page text-based button search
        result = await self._try_text_match(page, mode)
        if result is not None:
            return result

        # Strategy 10: Didomi JS API fallback
        result = await self._try_didomi_api(page, mode)
        if result is not None:
            return result

        # Strategy 11: Text-based search in iframes
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            result = await self._try_text_match_in_frame(frame, mode)
            if result is not None:
                return result

        # Strategy 12: Nested iframe CMPs (Sourcepoint, etc.)
        result = await self._try_nested_iframe_cmp(page, mode)
        if result is not None:
            return result

        logger.debug("No consent banner detected on %s", page.url)
        return ConsentInfo(banner_detected=False)

    # ─── Strategy: Known CMP on main page ────────────────────────────────

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

    # ─── Strategy: CMP in iframe ─────────────────────────────────────────

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

    # ─── Strategy: Shadow DOM banner piercing ────────────────────────────

    async def _try_shadow_dom_banner(
        self,
        page: Page,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Detect and interact with Shadow DOM-based consent banners.

        Uses page.evaluate() to pierce shadow boundaries and click buttons
        matching the text patterns. This is critical for Seznam's <szn-cwl>
        and similar custom web components.
        """
        texts = self._accept_texts if mode == ConsentMode.ACCEPT else self._reject_texts

        for selector in _SHADOW_DOM_HOSTS:
            try:
                result = await page.evaluate("""
                    ({selector, texts}) => {
                        const host = document.querySelector(selector);
                        if (!host) return null;

                        // Try open shadow root
                        const root = host.shadowRoot;
                        if (!root) return null;

                        const buttons = root.querySelectorAll(
                            'button, a, [role="button"], span[onclick], div[onclick]'
                        );

                        for (const btn of buttons) {
                            const btnText = (btn.innerText || btn.textContent || '').toLowerCase().trim();
                            if (!btnText) continue;

                            for (const pattern of texts) {
                                if (btnText.includes(pattern)) {
                                    btn.click();
                                    return {found: true, clicked: btnText, selector: selector};
                                }
                            }
                        }

                        // Banner found but no matching button in shadow root
                        return {found: true, clicked: false, selector: selector};
                    }
                """, {"selector": selector, "texts": texts})

                if result and result.get("found"):
                    clicked = result.get("clicked")
                    if clicked:
                        logger.info(
                            "Shadow DOM click: '%s' in %s on %s",
                            clicked, selector, page.url,
                        )
                        return ConsentInfo(
                            banner_detected=True,
                            cmp_platform=f"shadow_dom_{selector}",
                            button_text=str(clicked),
                            action_taken=True,
                        )
                    # Found shadow host but couldn't click — continue to other strategies
                    logger.debug("Shadow DOM host %s found but no matching button", selector)
            except Exception:
                continue

        return None

    # ─── Strategy: Two-step consent (Seznam redirect flow) ───────────────

    async def _try_two_step_consent(
        self,
        page: Page,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Handle two-step consent flows like Seznam's szn-cwl redirect.

        Seznam flow:
        1. Click initial <szn-cwl> shadow DOM dialog
        2. Wait for redirect to cmp.seznam.cz
        3. Click Souhlasím/Odmítnout on the CMP page
        """
        # ── Seznam two-step flow ──
        try:
            has_szn_cwl = await page.evaluate("""
                () => {
                    const cwl = document.querySelector('szn-cwl');
                    if (cwl && cwl.shadowRoot) {
                        const dialog = cwl.shadowRoot.querySelector(
                            '.cwl-dialog, .cwl-content, [class*="dialog"], [class*="banner"]'
                        );
                        if (dialog) {
                            dialog.click();
                            return true;
                        }
                        // Try clicking the host element itself
                        cwl.click();
                        return true;
                    }
                    return false;
                }
            """)

            if has_szn_cwl:
                logger.info("Seznam szn-cwl initial click on %s, waiting for CMP redirect...", page.url)
                await asyncio.sleep(3)

                # Check if redirected to CMP page
                if "cmp.seznam.cz" in page.url or "cmp." in page.url:
                    logger.info("Redirected to CMP page: %s", page.url)

                    # Approach A: Playwright's get_by_text pierces closed Shadow DOM
                    texts = self._accept_texts if mode == ConsentMode.ACCEPT else self._reject_texts
                    for text in texts:
                        try:
                            btn = page.get_by_text(text, exact=True)
                            if await btn.count() > 0:
                                await btn.first.click(timeout=5000)
                                logger.info("Seznam CMP: clicked '%s' via get_by_text", text)
                                return ConsentInfo(
                                    banner_detected=True,
                                    cmp_platform="seznam_cwl",
                                    button_text=text,
                                    action_taken=True,
                                )
                        except Exception:
                            continue

                    # Approach B: get_by_role
                    for text in texts:
                        try:
                            btn = page.get_by_role("button", name=text)
                            if await btn.count() > 0:
                                await btn.first.click(timeout=5000)
                                logger.info("Seznam CMP: clicked '%s' via get_by_role", text)
                                return ConsentInfo(
                                    banner_detected=True,
                                    cmp_platform="seznam_cwl",
                                    button_text=text,
                                    action_taken=True,
                                )
                        except Exception:
                            continue

                    # Approach C: Keyboard Tab+Enter
                    try:
                        await page.keyboard.press("Tab")
                        await asyncio.sleep(0.3)
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(2)
                        if "cmp" not in page.url:
                            logger.info("Seznam CMP: success via keyboard")
                            return ConsentInfo(
                                banner_detected=True,
                                cmp_platform="seznam_cwl",
                                button_text="keyboard",
                                action_taken=True,
                            )
                    except Exception:
                        pass

                    return ConsentInfo(
                        banner_detected=True,
                        cmp_platform="seznam_cwl",
                        action_taken=False,
                    )
        except Exception as e:
            logger.debug("Seznam two-step failed: %s", e)

        # ── Generic two-step: click "settings/manage" then find accept/reject ──
        settings_patterns = [
            "nastavit", "upravit", "nastavení", "volby", "spravovat",
            "manage", "customize", "settings", "options", "preferences",
        ]

        try:
            elements = page.locator(
                "button:visible, a:visible, [role='button']:visible"
            )
            count = await elements.count()

            for i in range(min(count, 40)):
                try:
                    el = elements.nth(i)
                    el_text = (await el.inner_text(timeout=300)).strip()
                    el_lower = el_text.lower()

                    if len(el_text) > 60:
                        continue

                    for pattern in settings_patterns:
                        if pattern in el_lower:
                            # Check if this is in a consent context
                            if await self._is_consent_context(el):
                                await el.click(timeout=3000)
                                logger.info("Two-step: clicked settings '%s'", el_text)
                                await asyncio.sleep(1.5)

                                # Now try standard text match for accept/reject
                                result = await self._try_text_match(page, mode)
                                if result is not None:
                                    result.cmp_platform = f"two_step_{result.cmp_platform}"
                                    return result
                                break
                except Exception:
                    continue
        except Exception:
            pass

        return None

    # ─── Strategy: Playwright get_by_text (pierces some Shadow DOM) ──────

    async def _try_get_by_text(
        self,
        page: Page,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Use Playwright's get_by_text() which can pierce some Shadow DOM boundaries.

        This is the breakthrough technique from the banner_detection_analysis:
        Playwright's get_by_text("Souhlasím", exact=True) CAN pierce closed
        Shadow DOM that regular locators can't reach.
        """
        texts = self._accept_texts if mode == ConsentMode.ACCEPT else self._reject_texts

        for text_pattern in texts:
            if text_pattern == "ok":
                continue
            try:
                # exact=False to do substring matching (like the text patterns)
                btn = page.get_by_text(text_pattern)
                count = await btn.count()
                if count == 0:
                    continue

                # Check the first few matches
                for i in range(min(count, 5)):
                    try:
                        el = btn.nth(i)
                        if not await el.is_visible(timeout=500):
                            continue

                        el_text = (await el.inner_text(timeout=500)).strip()
                        if len(el_text) > 80:
                            continue

                        # Verify this is in a consent-like context
                        if not await self._is_consent_context(el):
                            continue

                        await el.click(timeout=3000)
                        logger.info(
                            "get_by_text clicked: '%s' (pattern: '%s') on %s",
                            el_text, text_pattern, page.url,
                        )
                        return ConsentInfo(
                            banner_detected=True,
                            cmp_platform="get_by_text",
                            button_text=el_text,
                            action_taken=True,
                        )
                    except Exception:
                        continue
            except Exception:
                continue

        return None

    # ─── Strategy: Playwright get_by_role ─────────────────────────────────

    async def _try_get_by_role(
        self,
        page: Page,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Use Playwright's get_by_role() for accessible consent buttons."""
        texts = self._accept_texts if mode == ConsentMode.ACCEPT else self._reject_texts

        for text_pattern in texts:
            if text_pattern == "ok":
                continue
            try:
                btn = page.get_by_role("button", name=text_pattern)
                if await btn.count() > 0:
                    el = btn.first
                    if await el.is_visible(timeout=500):
                        if await self._is_consent_context(el):
                            el_text = (await el.inner_text(timeout=500)).strip()
                            await el.click(timeout=3000)
                            logger.info(
                                "get_by_role clicked: '%s' on %s",
                                el_text, page.url,
                            )
                            return ConsentInfo(
                                banner_detected=True,
                                cmp_platform="get_by_role",
                                button_text=el_text,
                                action_taken=True,
                            )
            except Exception:
                continue

        return None

    # ─── Strategy: Didomi JS API fallback ────────────────────────────────

    async def _try_didomi_api(
        self,
        page: Page,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Try the Didomi JavaScript API directly.

        Many Czech sites (iDNES, Denik, Heureka, Zive, CNC network) use Didomi.
        When the banner is hidden by anti-bot protections, the JS API may still work.
        """
        try:
            api_method = (
                "setUserAgreeToAll" if mode == ConsentMode.ACCEPT
                else "setUserDisagreeToAll"
            )
            result = await page.evaluate(f"""
                () => {{
                    if (window.Didomi && typeof window.Didomi.{api_method} === 'function') {{
                        window.Didomi.{api_method}();
                        return true;
                    }}
                    // Some sites expose __tcfapi
                    if (window.__tcfapi) {{
                        return 'tcfapi_present';
                    }}
                    return false;
                }}
            """)

            if result is True:
                logger.info("Didomi JS API: %s() on %s", api_method, page.url)
                return ConsentInfo(
                    banner_detected=True,
                    cmp_platform="didomi_api",
                    button_text=api_method,
                    action_taken=True,
                )
        except Exception:
            pass

        return None

    # ─── Strategy: CSS-based generic banner ──────────────────────────────

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

                container = banner.first
                texts = self._accept_texts if mode == ConsentMode.ACCEPT else self._reject_texts
                result = await self._find_button_in_container(container, texts, "css_banner")
                if result is not None:
                    return result
            except Exception:
                continue

        return None

    # ─── Strategy: Full-page text-based button search ────────────────────

    async def _try_text_match(
        self,
        page: Page,
        mode: ConsentMode,
    ) -> ConsentInfo | None:
        """Search the entire page for consent buttons by text content."""
        texts = self._accept_texts if mode == ConsentMode.ACCEPT else self._reject_texts

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

                        is_consent = await self._is_consent_context(el)
                        if not is_consent and len(el_text) < 4:
                            continue

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

    # ─── Strategy: Text-based search in iframes ──────────────────────────

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

    # ─── Strategy: Nested iframe CMP ─────────────────────────────────────

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

    # ─── Shared helpers ──────────────────────────────────────────────────

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
                    continue
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

    async def _is_consent_context(self, el: Locator) -> bool:
        """Check if an element sits inside a consent/cookie-related container."""
        try:
            result = await el.evaluate("""el => {
                const keywords = ['cookie', 'consent', 'gdpr', 'privacy', 'souhlas', 'soukrom',
                                   'cwl', 'cmp', 'didomi', 'onetrust', 'cookiebot'];
                let node = el.parentElement;
                for (let i = 0; i < 10 && node; i++) {
                    const cls = (node.className || '').toLowerCase();
                    const id = (node.id || '').toLowerCase();
                    const role = (node.getAttribute('role') || '').toLowerCase();
                    const tag = node.tagName.toLowerCase();
                    for (const kw of keywords) {
                        if (cls.includes(kw) || id.includes(kw) || tag.includes(kw)) return true;
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
