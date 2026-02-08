# Cookie Banner Detection Analysis & Manual

## Overview

This document analyzes how `footprint_crawler/consent.py` detects cookie consent banners and identifies gaps discovered through manual testing of Czech websites. The goal is to improve banner detection accuracy.

## Current Detection Strategies in `consent.py`

The current implementation uses **6 sequential strategies**:

| Strategy | Description | Strengths | Weaknesses |
|----------|-------------|-----------|------------|
| 1. Known CMPs | 14+ predefined CMP selectors (OneTrust, Cookiebot, etc.) | Fast, reliable for standard CMPs | Misses custom implementations |
| 2. Iframe CMPs | Same checks inside iframes | Catches embedded CMPs | Same limitations as above |
| 3. CSS-based | Matches `[id*='cookie-banner']`, `[class*='consent']`, etc. | Good for custom banners | May miss Shadow DOM |
| 4. Text matching | Searches visible buttons for Czech/English patterns | Language-aware | High false positive risk |
| 5. Iframe text | Text matching inside iframes | Catches iframe content | Same limitations |
| 6. Nested iframe | For CMPs like Sourcepoint in deep iframes | Handles complex structure | Performance cost |

### Currently Defined Text Patterns (Czech)

**Accept patterns:**
- "přijmout vše", "souhlasím", "accept all", "přijmout"
- "souhlasím se vším", "povolit vše", "Souhlasím", "Rozumím"
- "Přijmout a zavřít", "Přijmout cookies"

**Reject patterns:**
- "odmítnout vše", "odmítnout", "pouze nezbytné", "reject all"
- "nesouhlasím", "pouze technické", "jen nezbytné", "Odmítnout vše"

---

## Manual Testing Findings

### 1. Seznam.cz / Novinky.cz / Czech Seznam Properties

| Property | Value |
|----------|-------|
| **CMP Type** | Custom Shadow DOM (`<szn-cwl>`) |
| **Detection** | NOT COVERED by current strategies |
| **Flow** | TWO-STEP - initial banner hides action buttons |

**Technical Details:**
```html
<szn-cwl>
  #shadow-root (open)
    <div id="cwl-main">
      <!-- Initial state: info text, link to settings -->
      <!-- Action buttons hidden until user interaction -->
    </div>
</szn-cwl>
```

## 6. Confirmed Site-Specific Strategies (Feb 2026)

Based on manual testing, here are the proven strategies for major Czech sites:

| Site Group | CMP Type | Key Selectors | Strategy |
|------------|----------|---------------|----------|
| **Seznam.cz** | Custom (Shadow DOM) | `szn-cwl` (host) -> `.cwl-dialog` (trigger) -> `get_by_text("Souhlasím")` | **Piercing Shadow DOM**: Use Playwright's `get_by_text()` or deep JS piercing. Standard selectors fail. |
| **iDNES.cz** (Mafra) | Didomi (Custom Wall) | Trigger: `.cookie-info`<br>Accept: `.btn-cons.contentwall_ok` | **Two-Step**: Click small banner first, then accept on the full-screen content wall. |
| **Denik.cz** (VLM) | Didomi (Standard) | `#didomi-notice` -> `#didomi-notice-agree-button` | **Standard**: Wait for `.didomi-popup-container`, click agree button. Watch for OneSignal prompts. |
| **Heureka.cz** | Didomi (Standard) | `#didomi-notice` -> `#didomi-notice-agree-button` | **Standard**: Simple ID-based selection works reliably. |
| **Alza.cz** | Custom | `a.js-cookies-info-accept` | **Class Selector**: Use specific class or text "Rozumím". |
| **Zive.cz** (CNC) | Didomi (Global) | `#didomi-notice` (often hidden) | **Global Consent**: Checks cross-domain. Automation may be blocked (banner stays hidden). |

### Recommended Playwright Logic for Seznam
```python
# 1. Click initial banner (Open Shadow DOM)
await page.evaluate("document.querySelector('szn-cwl').shadowRoot.querySelector('.cwl-dialog').click()")
# 2. Wait for CMP redirect
await page.wait_for_url("**/cmp.seznam.cz/**")
# 3. Click Accept (Pierce Closed Shadow DOM)
await page.get_by_text("Souhlasím", exact=True).click()
```

**Key Issues:**
1. **Shadow DOM** - `page.locator()` cannot pierce shadow boundaries by default
2. **Two-step flow** - Accept/Reject buttons only appear after clicking "Nastavit volby" or similar
3. **Redirect flow** - Often redirects to `cmp.seznam.cz/nastaveni-souhlasu` for detailed settings

**Recommended Detection:**
```python
# Detect szn-cwl shadow host
detect_selector = "szn-cwl"

# Need to pierce shadow DOM
await page.evaluate("""
    const host = document.querySelector('szn-cwl');
    if (host?.shadowRoot) {
        const btn = host.shadowRoot.querySelector('button, [role="button"]');
        if (btn) btn.click();
    }
""")
```

---

### 2. Alza.cz

| Property | Value |
|----------|-------|
| **CMP Type** | Custom internal (`window.Alza.Web.Cookies`) |
| **Banner Selector** | `div.js-cookies-info.cookies-info` |
| **Accept Button** | `a.js-cookies-info-accept` → "Rozumím" |
| **Reject Button** | `a.js-cookies-info-reject` → "Odmítnout vše" |

**Key Issues:**
1. **Buttons are `<a>` tags**, not `<button>` - current text matching includes `a:visible` ✓
2. **Uses `href="javascript:..."` pattern**
3. **JS API available:** `Alza.Web.Cookies.acceptAllCookies()`

**Detection Status:** Should be caught by text matching ("Rozumím" pattern), but adding explicit CSS selector would be more reliable:

```python
_CMP_DEFINITIONS.append(_CMPDefinition(
    name="alza",
    detect_selector="div.js-cookies-info, .cookies-info",
    accept_selectors=["a.js-cookies-info-accept", ".js-cookies-info-accept"],
    reject_selectors=["a.js-cookies-info-reject", ".js-cookies-info-reject"],
))
```

---

## Gap Analysis Summary

### ❌ Not Currently Covered

| Gap | Impact | Sites Affected |
|-----|--------|----------------|
| **Shadow DOM banners** | High | Seznam.cz, Novinky.cz, likely more |
| **Two-step consent flows** | High | Seznam properties, some others |
| **Custom CMP definitions** | Medium | Alza, other Czech e-commerce |
| **Web Components** | Medium | Modern custom elements |

### ⚠️ Partially Covered

| Gap | Current Behavior | Risk |
|-----|------------------|------|
| Generic text matching | Works but may click wrong buttons | False positives |
| Czech text variants | Basic patterns only | May miss dialectal variations |

---

## Recommendations for Improved Detection

### 1. Add Shadow DOM Support

```python
async def _try_shadow_dom_banner(self, page: Page, mode: ConsentMode) -> ConsentInfo | None:
    """Detect and interact with Shadow DOM-based consent banners."""
    
    # Known Shadow DOM CMP selectors
    shadow_hosts = ["szn-cwl", "cookie-consent-widget", "[data-consent-shadow]"]
    
    for selector in shadow_hosts:
        result = await page.evaluate(f"""
            (selector, acceptTexts, rejectTexts, mode) => {{
                const host = document.querySelector(selector);
                if (!host?.shadowRoot) return null;
                
                const root = host.shadowRoot;
                const buttons = root.querySelectorAll('button, a, [role="button"]');
                const texts = mode === 'accept' ? acceptTexts : rejectTexts;
                
                for (const btn of buttons) {{
                    const btnText = btn.innerText.toLowerCase();
                    for (const pattern of texts) {{
                        if (btnText.includes(pattern)) {{
                            btn.click();
                            return {{ found: true, clicked: btnText }};
                        }}
                    }}
                }}
                return {{ found: true, clicked: false }};
            }}
        """, selector, self._accept_texts, self._reject_texts, mode.value)
        
        if result and result.get('found'):
            return ConsentInfo(
                banner_detected=True,
                cmp_platform=f"shadow_dom_{selector}",
                button_text=result.get('clicked', ''),
                action_taken=bool(result.get('clicked')),
            )
    
    return None
```

### 2. Add Two-Step Flow Support

```python
async def _handle_two_step_consent(self, page: Page, mode: ConsentMode) -> ConsentInfo | None:
    """Handle CMPs that require two clicks (settings then accept/reject)."""
    
    # First, look for "settings" or "customize" buttons
    settings_patterns = [
        "nastavit", "upravit", "nastavení", "volby",
        "manage", "customize", "settings", "options"
    ]
    
    # Click settings button first
    settings_clicked = await self._click_settings_button(page, settings_patterns)
    
    if settings_clicked:
        await asyncio.sleep(1)  # Wait for panel transition
        # Now try normal detection strategies again
        return await self._try_text_match(page, mode)
    
    return None
```

### 3. Add Czech-Specific CMP Definitions

```python
# Add to _CMP_DEFINITIONS
_CMPDefinition(
    name="seznam_cwl",
    detect_selector="szn-cwl",
    accept_selectors=[],  # Requires shadow DOM handling
    reject_selectors=[],
),
_CMPDefinition(
    name="alza",
    detect_selector="div.js-cookies-info, .cookies-info",
    accept_selectors=["a.js-cookies-info-accept"],
    reject_selectors=["a.js-cookies-info-reject"],
),
```

### 4. Expand Czech Text Patterns

```python
# Additional patterns to add
accept_patterns_extra = [
    "pokračovat",  # Continue (used by Seznam)
    "přijímám",    # I accept (formal)
    "ano, souhlasím",
    "přijmout všechny",
    "akceptovat",
]

reject_patterns_extra = [
    "jen nezbytné cookies",
    "pouze základní",
    "zamítnout",
    "nepřijímám",
    "pokračovat bez souhlasu",
]
```

---

## Testing Checklist for Banner Detection

When manually verifying banner detection:

1. **[ ] Does the banner use Shadow DOM?**
   - Open DevTools → check for `#shadow-root` in Elements panel
   
2. **[ ] Is it a multi-step flow?**
   - Note if you need to click "settings" before seeing accept/reject
   
3. **[ ] What element types are the buttons?**
   - `<button>`, `<a>`, `<div onclick>`, `<span>`, etc.
   
4. **[ ] Is the banner inside an iframe?**
   - Check for `<iframe>` wrapper in DOM
   
5. **[ ] What is the banner container selector?**
   - ID, class, or data attributes
   
6. **[ ] What are the exact button texts?**
   - Record both Czech and any English variants

---

## Files Analyzed

| File | Purpose |
|------|---------|
| `footprint_crawler/consent.py` | Main banner detection logic |
| `footprint_crawler/config.py` | Text patterns configuration |
| `data/sites/czech_top_100.csv` | Site list for testing |

---

*Report generated: 2026-02-08*
*Sites tested: Seznam.cz, Novinky.cz, Alza.cz*
