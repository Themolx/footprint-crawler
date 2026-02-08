#!/usr/bin/env python3
"""
Test Alza.cz Consent (Custom Implementation).
Alza uses a custom "Alza.Web.Cookies" implementation with specific classes.
"""

import asyncio
from playwright.async_api import async_playwright

async def click_alza_consent():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="cs-CZ",
        )
        page = await context.new_page()
        
        print("\n" + "="*60)
        print("Testing: https://www.alza.cz")
        print("="*60)
        
        print("1. Navigating...")
        await page.goto("https://www.alza.cz", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        print("2. Checking for cookie banner...")
        
        # Alza uses .js-cookies-info container
        # Accept button is a.js-cookies-info-accept
        try:
            accept_btn = page.locator("a.js-cookies-info-accept")
            
            if await accept_btn.count() > 0 and await accept_btn.is_visible():
                print("   Found accept button (a.js-cookies-info-accept)")
                await accept_btn.click()
                print("   ✅ CLICKED accept button")
                
                await page.wait_for_timeout(2000)
                
                # Verify visibility
                if not await accept_btn.is_visible():
                    print("   ✅ Banner is gone")
                    
                    # Verify cookie (Alza often uses custom cookies + TCF)
                    cookies = await page.context.cookies()
                    found_cookies = [c['name'] for c in cookies if 'consent' in c['name'].lower() or 'cookie' in c['name'].lower()]
                    print(f"   Found related cookies: {found_cookies}")
                else:
                    print("   ❌ Banner still visible")
            else:
                # Fallback to Text search
                print("   ⚠️  Class selector not found, trying text 'Rozumím'...")
                text_btn = page.get_by_text("Rozumím", exact=True)
                if await text_btn.count() > 0 and await text_btn.is_visible():
                    await text_btn.click()
                    print("   ✅ CLICKED 'Rozumím' button")
                else:
                    print("   ❌ Alza banner not found")
                    await page.screenshot(path="alza_debug.png")

        except Exception as e:
            print(f"   ❌ Error searching/clicking banner: {e}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(click_alza_consent())
