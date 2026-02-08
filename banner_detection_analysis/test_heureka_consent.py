#!/usr/bin/env python3
"""
Test Heureka.cz Consent (Standard Didomi).
Heureka uses a standard Didomi banner implementation.
"""

import asyncio
from playwright.async_api import async_playwright

async def click_heureka_consent():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="cs-CZ",
        )
        page = await context.new_page()
        
        print("\n" + "="*60)
        print("Testing: https://www.heureka.cz")
        print("="*60)
        
        print("1. Navigating...")
        await page.goto("https://www.heureka.cz", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        # Check for Didomi
        has_didomi = await page.evaluate("!!window.Didomi")
        print(f"2. Has Didomi: {has_didomi}")
        
        # Looking for banner
        print("3. Looking for banner...")
        
        try:
            # Heureka uses standard #didomi-notice and #didomi-notice-agree-button
            accept_btn = page.locator("#didomi-notice-agree-button")
            
            if await accept_btn.count() > 0 and await accept_btn.is_visible():
                print("   Found accept button (#didomi-notice-agree-button)")
                await accept_btn.click()
                print("   ✅ CLICKED accept button")
                
                await page.wait_for_timeout(2000)
                
                # Check visibility
                if not await accept_btn.is_visible():
                    print("   ✅ Banner is gone")
                    
                    # Verify cookie
                    has_cookie = await page.evaluate("document.cookie.includes('euconsent-v2')")
                    print(f"   Cookie 'euconsent-v2' present: {has_cookie}")
                else:
                    print("   ❌ Banner still visible")
            else:
                 print("   ❌ Accept button not found or not visible")
                 # Check if maybe already consented
                 if await page.evaluate("document.cookie.includes('euconsent-v2')"):
                     print("   ⚠️  Already consented (cookie present)")
                 else:
                     await page.screenshot(path="heureka_debug.png")
                     print("   Saved debug screenshot")

        except Exception as e:
            print(f"   ❌ Error: {e}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(click_heureka_consent())
