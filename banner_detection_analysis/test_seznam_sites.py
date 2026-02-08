#!/usr/bin/env python3
"""
Test Seznam CMP consent on multiple Seznam properties.
The same <szn-cwl> Shadow DOM approach should work on all Seznam sites.
"""

import asyncio
from playwright.async_api import async_playwright


SEZNAM_SITES = [
    "https://www.novinky.cz",
    "https://www.stream.cz", 
    "https://www.sport.cz",
    "https://www.super.cz",
]


async def click_seznam_consent(page, site_url: str) -> dict:
    """Click consent on a Seznam property using the szn-cwl approach."""
    result = {"site": site_url, "success": False, "method": None, "error": None}
    
    try:
        print(f"\n{'='*60}")
        print(f"Testing: {site_url}")
        print('='*60)
        
        print("1. Navigating...")
        await page.goto(site_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        # Check if there's an szn-cwl element
        has_cwl = await page.evaluate("() => !!document.querySelector('szn-cwl')")
        print(f"2. Has <szn-cwl> banner: {has_cwl}")
        
        if not has_cwl:
            # Maybe consent already given or different CMP
            result["error"] = "No szn-cwl banner found (maybe already consented?)"
            return result
        
        # Click the initial banner (open Shadow DOM)
        print("3. Clicking initial szn-cwl banner...")
        clicked = await page.evaluate("""
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
        
        if not clicked:
            result["error"] = "Could not click initial szn-cwl dialog"
            return result
        
        await page.wait_for_timeout(3000)
        print(f"4. Current URL: {page.url}")
        
        # Check if we're on the CMP page
        if "cmp.seznam.cz" in page.url:
            print("5. On CMP page, looking for 'Souhlasím' button...")
            
            # Use get_by_text which can pierce shadow DOM
            try:
                btn = page.get_by_text("Souhlasím", exact=True)
                count = await btn.count()
                print(f"   Found {count} 'Souhlasím' button(s)")
                
                if count > 0:
                    await btn.first.click(timeout=5000)
                    result["success"] = True
                    result["method"] = "get_by_text"
                    print("   ✅ CLICKED!")
            except Exception as e:
                print(f"   get_by_text failed: {e}")
                result["error"] = str(e)
            
            await page.wait_for_timeout(2000)
            print(f"6. Final URL: {page.url}")
            
            # Check if we returned to original site
            if result["success"] and "cmp.seznam.cz" not in page.url:
                print("   ✅ Successfully returned to original site!")
        else:
            result["error"] = f"Did not navigate to CMP page, stayed at {page.url}"
            
    except Exception as e:
        result["error"] = str(e)
        print(f"   ❌ Error: {e}")
    
    return result


async def run_tests():
    """Run consent tests on all Seznam sites."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="cs-CZ",
        )
        page = await context.new_page()
        
        results = []
        
        for site in SEZNAM_SITES:
            # Clear cookies between tests to ensure banner appears
            await context.clear_cookies()
            result = await click_seznam_consent(page, site)
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
            error = f" | {r['error']}" if r["error"] else ""
            print(f"{r['site']}: {status}{error}")
        
        print(f"\nTotal: {success_count}/{len(results)} successful")
        return results


if __name__ == "__main__":
    asyncio.run(run_tests())
