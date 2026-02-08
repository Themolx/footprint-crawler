#!/usr/bin/env python3
"""
Test iDNES.cz Consent / Content Wall.
iDNES uses a custom "Content Wall" that requires clicking an initial banner
to reveal the options, then clicking "Souhlasím".
"""

import asyncio
from playwright.async_api import async_playwright

async def click_idnes_consent():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="cs-CZ",
        )
        page = await context.new_page()
        
        print("\n" + "="*60)
        print("Testing: https://www.idnes.cz")
        print("="*60)
        
        print("1. Navigating...")
        await page.goto("https://www.idnes.cz", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        # Check for initial banner
        print("2. Checking for initial banner...")
        
        # iDNES often has a small bottom banner .cookie-info or straight to content wall
        cookie_info = page.locator(".cookie-info")
        content_wall = page.locator("#content-wall, .content-wall")
        
        if await cookie_info.count() > 0 and await cookie_info.is_visible():
            print("   Found .cookie-info banner, clicking to reveal wall...")
            await cookie_info.click()
            await page.wait_for_timeout(1000)
        
        # Now check for valid consent buttons in the Content Wall
        # Selector found: .btn-cons.contentwall_ok
        print("3. Looking for Content Wall accept button...")
        
        try:
            accept_btn = page.locator(".btn-cons.contentwall_ok")
            
            if await accept_btn.count() > 0 and await accept_btn.is_visible():
                print("   Found accept button (.btn-cons.contentwall_ok)")
                await accept_btn.click()
                print("   ✅ CLICKED accept button")
                
                await page.wait_for_timeout(3000)
                
                # Verify overlay is gone
                if not await accept_btn.is_visible():
                    print("   ✅ Content Wall/Banner is gone")
                    
                    # Verify cookie
                    has_cookie = await page.evaluate("document.cookie.includes('euconsent-v2')")
                    print(f"   Cookie 'euconsent-v2' present: {has_cookie}")
                else:
                    print("   ❌ Button still visible after click")
            else:
                print("   ⚠️  Accept button not found directly.")
                
                # Check if maybe we are already in Didomi logic
                # Try standard Didomi selector just in case
                didomi_btn = page.locator("#didomi-notice-agree-button")
                if await didomi_btn.count() > 0 and await didomi_btn.is_visible():
                    print("   Found standard Didomi button instead")
                    await didomi_btn.click()
                    print("   ✅ CLICKED Didomi button")
                else:
                     print("   ❌ No recognized consent button found")
                     # Debug screenshot
                     await page.screenshot(path="idnes_debug.png")
                     print("   Saved debug screenshot to idnes_debug.png")

        except Exception as e:
            print(f"   ❌ Error searching/clicking banner: {e}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(click_idnes_consent())
