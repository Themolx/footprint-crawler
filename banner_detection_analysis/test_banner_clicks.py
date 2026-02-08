#!/usr/bin/env python3
"""
Test script for clicking cookie consent banners on Czech websites.
Uses Playwright to handle Shadow DOM and two-step consent flows.
"""

import asyncio
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout


async def click_seznam_consent(page: Page) -> dict:
    """
    Handle Seznam.cz's two-step Shadow DOM consent flow.
    
    Seznam uses:
    1. Initial banner in <szn-cwl> with open Shadow DOM
    2. Redirects to cmp.seznam.cz with closed Shadow DOM
    """
    result = {"site": "seznam.cz", "success": False, "method": None, "error": None}
    
    try:
        await page.goto("https://www.seznam.cz", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)  # Wait for banner to appear
        
        print("[Seznam] Looking for initial <szn-cwl> banner...")
        
        # Step 1: Click initial banner to reveal options (it's in open Shadow DOM)
        clicked_initial = await page.evaluate("""
            () => {
                const cwl = document.querySelector('szn-cwl');
                if (cwl && cwl.shadowRoot) {
                    const dialog = cwl.shadowRoot.querySelector('.cwl-dialog');
                    if (dialog) {
                        dialog.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        
        if clicked_initial:
            print("[Seznam] Clicked initial banner, waiting for CMP page...")
            await page.wait_for_timeout(3000)
            
            # Check if we're on the CMP page
            if "cmp.seznam.cz" in page.url:
                print(f"[Seznam] Now on CMP page: {page.url}")
                
                # Step 2: The CMP page uses a div.szn-cmp-dialog-container
                # Try multiple approaches to click "Souhlasím"
                
                # Approach A: Use Playwright's built-in text locator (pierces some shadow DOM)
                try:
                    souhlasim_btn = page.get_by_text("Souhlasím", exact=True)
                    await souhlasim_btn.click(timeout=5000)
                    result["success"] = True
                    result["method"] = "get_by_text"
                    print("[Seznam] SUCCESS via get_by_text!")
                except PlaywrightTimeout:
                    print("[Seznam] get_by_text failed, trying JS approach...")
                
                # Approach B: Use JavaScript to find and click in closed Shadow DOM
                if not result["success"]:
                    clicked = await page.evaluate("""
                        () => {
                            // Try clicking by coordinates using elementFromPoint
                            // The Souhlasím button is roughly at these coordinates
                            const container = document.querySelector('.szn-cmp-dialog-container');
                            if (container) {
                                // Dispatch a click event directly
                                const rect = container.getBoundingClientRect();
                                const centerX = rect.left + rect.width / 2;
                                const centerY = rect.top + 300; // Approximate button location
                                
                                const clickEvent = new MouseEvent('click', {
                                    bubbles: true,
                                    cancelable: true,
                                    view: window,
                                    clientX: centerX,
                                    clientY: centerY
                                });
                                container.dispatchEvent(clickEvent);
                                return 'dispatched_click';
                            }
                            return false;
                        }
                    """)
                    
                    if clicked:
                        await page.wait_for_timeout(2000)
                        # Check if we're back on seznam.cz (indicating success)
                        if "seznam.cz" in page.url and "cmp" not in page.url:
                            result["success"] = True
                            result["method"] = "js_dispatch_click"
                            print("[Seznam] SUCCESS via JS dispatch!")
                
                # Approach C: Use keyboard navigation
                if not result["success"]:
                    print("[Seznam] Trying keyboard navigation...")
                    await page.keyboard.press("Tab")
                    await page.wait_for_timeout(300)
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(2000)
                    
                    if "seznam.cz" in page.url and "cmp" not in page.url:
                        result["success"] = True
                        result["method"] = "keyboard"
                        print("[Seznam] SUCCESS via keyboard!")
                
                # Approach D: Use page.click with force and position
                if not result["success"]:
                    print("[Seznam] Trying forced pixel click...")
                    try:
                        # Click at approximate button location
                        await page.mouse.click(284, 661)
                        await page.wait_for_timeout(2000)
                        
                        if "seznam.cz" in page.url and "cmp" not in page.url:
                            result["success"] = True
                            result["method"] = "mouse_click"
                            print("[Seznam] SUCCESS via mouse click!")
                    except Exception as e:
                        print(f"[Seznam] Mouse click failed: {e}")
            else:
                result["error"] = "Did not navigate to CMP page"
        else:
            result["error"] = "Could not find/click initial szn-cwl banner"
            
    except Exception as e:
        result["error"] = str(e)
        print(f"[Seznam] Error: {e}")
    
    return result


async def click_alza_consent(page: Page) -> dict:
    """
    Handle Alza.cz's custom consent banner.
    Uses standard DOM with .js-cookies-info-accept selector.
    """
    result = {"site": "alza.cz", "success": False, "method": None, "error": None}
    
    try:
        await page.goto("https://www.alza.cz", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        print("[Alza] Looking for cookie banner...")
        
        # Alza uses a simple custom banner with .js-cookies-info-accept
        try:
            accept_btn = page.locator("a.js-cookies-info-accept")
            if await accept_btn.count() > 0 and await accept_btn.is_visible():
                await accept_btn.click()
                result["success"] = True
                result["method"] = "css_selector"
                print("[Alza] SUCCESS via CSS selector!")
        except PlaywrightTimeout:
            pass
        
        # Fallback: text search
        if not result["success"]:
            try:
                rozumim_btn = page.get_by_text("Rozumím")
                await rozumim_btn.click(timeout=3000)
                result["success"] = True
                result["method"] = "get_by_text"
                print("[Alza] SUCCESS via get_by_text!")
            except PlaywrightTimeout:
                result["error"] = "Could not find accept button"
                
    except Exception as e:
        result["error"] = str(e)
        print(f"[Alza] Error: {e}")
    
    return result


async def click_idnes_consent(page: Page) -> dict:
    """
    Handle iDNES.cz's consent banner.
    Uses Didomi CMP with Shadow DOM.
    """
    result = {"site": "idnes.cz", "success": False, "method": None, "error": None}
    
    try:
        await page.goto("https://www.idnes.cz", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        print("[iDNES] Looking for Didomi consent banner...")
        
        # iDNES uses Didomi which has a #didomi-host shadow DOM
        # Try standard Playwright approach first
        try:
            accept_btn = page.get_by_role("button", name="Souhlasím")
            await accept_btn.click(timeout=5000)
            result["success"] = True
            result["method"] = "get_by_role"
            print("[iDNES] SUCCESS via get_by_role!")
        except PlaywrightTimeout:
            pass
        
        # Try text search
        if not result["success"]:
            try:
                accept_btn = page.get_by_text("Souhlasím", exact=True)
                await accept_btn.click(timeout=3000)
                result["success"] = True
                result["method"] = "get_by_text"
                print("[iDNES] SUCCESS via get_by_text!")
            except PlaywrightTimeout:
                pass
        
        # Try JS approach for Didomi
        if not result["success"]:
            clicked = await page.evaluate("""
                () => {
                    // Check for Didomi API
                    if (window.Didomi) {
                        window.Didomi.setUserAgreeToAll();
                        return 'didomi_api';
                    }
                    
                    // Check for didomi-host shadow DOM
                    const host = document.getElementById('didomi-host');
                    if (host && host.shadowRoot) {
                        const btns = host.shadowRoot.querySelectorAll('button');
                        for (const btn of btns) {
                            if (btn.innerText.includes('Souhlasím')) {
                                btn.click();
                                return 'shadow_click';
                            }
                        }
                    }
                    
                    return false;
                }
            """)
            
            if clicked:
                result["success"] = True
                result["method"] = f"js_{clicked}"
                print(f"[iDNES] SUCCESS via JS ({clicked})!")
            else:
                result["error"] = "Could not find Didomi banner or API"
                
    except Exception as e:
        result["error"] = str(e)
        print(f"[iDNES] Error: {e}")
    
    return result


async def click_csob_consent(page: Page) -> dict:
    """Handle CSOB.cz consent banner."""
    result = {"site": "csob.cz", "success": False, "method": None, "error": None}
    
    try:
        await page.goto("https://www.csob.cz", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        print("[CSOB] Looking for consent banner...")
        
        # Try common patterns
        for selector in [
            "#onetrust-accept-btn-handler",
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "button:has-text('Přijmout')",
            "button:has-text('Souhlasím')",
            "a:has-text('Rozumím')",
        ]:
            try:
                btn = page.locator(selector)
                if await btn.count() > 0:
                    await btn.click(timeout=3000)
                    result["success"] = True
                    result["method"] = f"selector:{selector}"
                    print(f"[CSOB] SUCCESS via {selector}!")
                    break
            except:
                continue
        
        # Fallback: generic text search
        if not result["success"]:
            for text in ["Přijmout všechny", "Souhlasím", "Rozumím"]:
                try:
                    btn = page.get_by_text(text)
                    await btn.first.click(timeout=2000)
                    result["success"] = True
                    result["method"] = f"text:{text}"
                    print(f"[CSOB] SUCCESS via text '{text}'!")
                    break
                except:
                    continue
        
        if not result["success"]:
            result["error"] = "No matching consent button found"
                
    except Exception as e:
        result["error"] = str(e)
        print(f"[CSOB] Error: {e}")
    
    return result


async def run_tests():
    """Run consent click tests on multiple sites."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # Use headless=True for CI
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="cs-CZ",
        )
        
        page = await context.new_page()
        
        results = []
        
        # Test each site
        print("=" * 60)
        print("TESTING COOKIE BANNER CLICKS")
        print("=" * 60)
        
        # Seznam
        print("\n--- Testing Seznam.cz ---")
        results.append(await click_seznam_consent(page))
        await page.wait_for_timeout(1000)
        
        # Alza
        print("\n--- Testing Alza.cz ---")
        results.append(await click_alza_consent(page))
        await page.wait_for_timeout(1000)
        
        # iDNES
        print("\n--- Testing iDNES.cz ---")
        results.append(await click_idnes_consent(page))
        await page.wait_for_timeout(1000)
        
        # CSOB
        print("\n--- Testing CSOB.cz ---")
        results.append(await click_csob_consent(page))
        
        await browser.close()
        
        # Summary
        print("\n" + "=" * 60)
        print("RESULTS SUMMARY")
        print("=" * 60)
        for r in results:
            status = "✅ SUCCESS" if r["success"] else "❌ FAILED"
            method = r["method"] or "N/A"
            error = r["error"] or ""
            print(f"{r['site']}: {status} | Method: {method} {(' | Error: ' + error) if error else ''}")
        
        return results


if __name__ == "__main__":
    asyncio.run(run_tests())
