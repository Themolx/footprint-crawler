# Manual Testing Notes

## ✅ PLAYWRIGHT SUCCESS: Seznam.cz 

**The Playwright script successfully clicked the consent banner!**

### Key Finding
Playwright's `get_by_text("Souhlasím", exact=True)` **can pierce the closed Shadow DOM** that the browser subagent couldn't access.

### Successful Approach
```python
# Step 1: Click initial szn-cwl shadow DOM banner
await page.evaluate("""
    const cwl = document.querySelector('szn-cwl');
    if (cwl && cwl.shadowRoot) {
        const dialog = cwl.shadowRoot.querySelector('.cwl-dialog');
        dialog.click();
    }
""")

# Step 2: Wait for CMP page redirect
await page.wait_for_timeout(3000)

# Step 3: Click "Souhlasím" - Playwright pierces shadow DOM!
btn = page.get_by_text("Souhlasím", exact=True)
await btn.first.click()  # SUCCESS!
```

### Screenshots
- `before_click.png` - Homepage with initial banner
- `cmp_page.png` - CMP page with consent options
- `after_click.png` - Homepage after consent (no banner!)

## ❌ Zive.cz Network (Didomi) - FAILED

**Status:** Script failed to detect visible banner. 
**Issue:** `window.Didomi.notice.show()` was called but banner remained hidden or undetectable by Playwright.
**Next Steps:** Investigate iframes or specific anti-bot protections.

## ✅ Denik.cz (Didomi) - SUCCESS

**CMP:** Standard Didomi
**Selector:** `.didomi-popup-container` -> `#didomi-notice-agree-button`
**Result:** Successfully clicked "Souhlasím". Confirmed by `euconsent-v2` cookie.
**Note:** OneSignal prompt appears after consent (not blocking).

## ✅ iDNES.cz (Didomi / Custom Content Wall) - SUCCESS

**CMP:** Didomi (custom implementation)
**Selectors:**
- Trigger: `.cookie-info` (small bottom banner)
- Accept: `.btn-cons.contentwall_ok` (on overlay)
**Result:** Successfully clicked triggers then accept button. Confirmed by `euconsent-v2` cookie.
**Note:** No Shadow DOM involved, just custom overlay structure.

## ✅ Heureka.cz (Didomi) - SUCCESS

**CMP:** Standard Didomi
**Selector:** `#didomi-notice-agree-button`
**Result:** Successfully clicked "Souhlasit a zavřít". Confirmed by `euconsent-v2` cookie.
**Note:** Single-step flow, no Shadow DOM.

## ✅ Alza.cz (Custom) - SUCCESS

**CMP:** Custom implementation (`Alza.Web.Cookies`)
**Selectors:** `a.js-cookies-info-accept` OR text "Rozumím"
**Result:** Successfully clicked accept button. Banner removed.
**Note:** Uses custom cookies + potentially TCF.

---

## Sites Tested (2026-02-08)

### 1. Seznam.cz ✓
- **Recording:** [seznam_banner_1770578601904.webp](./seznam_banner_1770578601904.webp)
- **CMP:** Custom Shadow DOM (`<szn-cwl>`)
- **Key finding:** Two-step flow - must click to reveal accept/reject buttons
- **Not covered** by current detection

### 2. Alza.cz ✓ 
- **Screenshot:** [alza_homepage_v1_1770578897600.png](./alza_homepage_v1_1770578897600.png)
- **Recording:** [alza_banner_1770578897600.webp](./alza_banner_1770578897600.webp)
- **CMP:** Custom (`window.Alza.Web.Cookies`)
- **Selectors:** `.js-cookies-info-accept`, `.js-cookies-info-reject`
- **Partially covered** by text matching

### 3. Novinky.cz ✓
- **Recording:** [novinky_banner_1770578940762.webp](./novinky_banner_1770578940762.webp)
- **CMP:** Same Seznam Shadow DOM (`<szn-cwl>`)
- **Key finding:** Same two-step flow as Seznam.cz
- **Not covered** by current detection

---

## Priority Sites for Future Testing

| Category | Sites to Test |
|----------|--------------|
| **News** | idnes.cz, aktualne.cz, irozhlas.cz |
| **E-commerce** | mall.cz, czc.cz, rohlik.cz |
| **Banks** | csob.cz, kb.cz, csas.cz |
| **Government** | gov.cz, portal.gov.cz |
| **Telecom** | o2.cz, t-mobile.cz, vodafone.cz |
