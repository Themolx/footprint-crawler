#!/usr/bin/env python3
"""
Test Didomi CMP consent on CN Center sites (zive.cz network).
These sites use standard DOM Didomi with global consent across the network.
"""

import asyncio
from playwright.async_api import async_playwright


# CN Center / Didomi sites
ZIVE_NETWORK_SITES = [
    "https://www.zive.cz",
    "https://www.blesk.cz",
    "https://www.auto.cz",
    "https://www.isport.cz",
    "https://www.reflex.cz",
]


async def click_didomi_consent(page, site_url: str) -> dict:
    """Click consent on a Didomi-powered site."""
    result = {"site": site_url, "success": False, "method": None, "error": None}
    
    try:
        print(f"\n{'='*60}")
        print(f"Testing: {site_url}")
        print('='*60)
        
        print("1. Navigating...")
        await page.goto(site_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        # Check for Didomi banner
        has_didomi = await page.evaluate("() => !!window.Didomi")
        print(f"2. Has Didomi: {has_didomi}")
        
        # Check if notice is visible
        notice_visible = await page.evaluate("""
            () => {
                const notice = document.querySelector('#didomi-notice');
                return notice && notice.offsetHeight > 0;
            }
        """)
        print(f"3. Notice visible: {notice_visible}")
        
        if not notice_visible:
            # Try to force show it
            await page.evaluate("() => window.Didomi?.notice?.show()")
            await page.wait_for_timeout(1000)
            notice_visible = await page.evaluate("""
                () => {
                    const notice = document.querySelector('#didomi-notice');
                    return notice && notice.offsetHeight > 0;
                }
            """)
            print(f"   After force show: {notice_visible}")
        
        if notice_visible:
            # Click the accept button
            print("4. Clicking accept button...")
            try:
                btn = page.locator("#didomi-notice-agree-button")
                await btn.click(timeout=5000)
                result["success"] = True
                result["method"] = "css_selector"
                print("   ✅ CLICKED via #didomi-notice-agree-button!")
            except Exception as e:
                print(f"   CSS selector failed: {e}")
                
                # Fallback: text search
                try:
                    btn = page.get_by_text("Rozumím a přijímám")
                    await btn.click(timeout=3000)
                    result["success"] = True
                    result["method"] = "get_by_text"
                    print("   ✅ CLICKED via get_by_text!")
                except Exception as e2:
                    print(f"   Text fallback failed: {e2}")
                    
                    # Final fallback: JS click
                    clicked = await page.evaluate("""
                        () => {
                            const btn = document.getElementById('didomi-notice-agree-button');
                            if (btn) { btn.click(); return true; }
                            return false;
                        }
                    """)
                    if clicked:
                        result["success"] = True
                        result["method"] = "js_click"
                        print("   ✅ CLICKED via JS!")
            
            await page.wait_for_timeout(1000)
            
            # Verify consent was set
            has_consent = await page.evaluate("""
                () => document.cookie.includes('euconsent-v2')
            """)
            print(f"5. euconsent-v2 cookie set: {has_consent}")
            
        else:
            # Check if already consented (global consent from another site)
            has_consent = await page.evaluate("""
                () => document.cookie.includes('euconsent-v2')
            """)
            if has_consent:
                result["success"] = True
                result["method"] = "already_consented"
                print("4. Already has consent (global consent)")
            else:
                result["error"] = "Notice not visible and no existing consent"
            
    except Exception as e:
        result["error"] = str(e)
        print(f"   ❌ Error: {e}")
    
    return result


async def run_tests():
    """Run consent tests on all CN Center sites."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="cs-CZ",
        )
        page = await context.new_page()
        
        results = []
        
        for site in ZIVE_NETWORK_SITES:
            # Clear cookies between tests to ensure banner appears fresh
            await context.clear_cookies()
            result = await click_didomi_consent(page, site)
            results.append(result)
        
        await browser.close()
        
        # Summary
        print("\n" + "="*60)
        print("RESULTS SUMMARY")
        print("="*60)
        
        success_count = 0
        for r in results:
            status = "✅ SUCCESS" if r["success"] else "❌ FAILED"
            if r["success"]:
                success_count += 1
            method = r["method"] or "N/A"
            error = f" | {r['error']}" if r["error"] else ""
            print(f"{r['site']}: {status} | Method: {method}{error}")
        
        print(f"\nTotal: {success_count}/{len(results)} successful")
        return results


if __name__ == "__main__":
    asyncio.run(run_tests())
