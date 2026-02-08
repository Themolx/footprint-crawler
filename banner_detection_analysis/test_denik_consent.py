#!/usr/bin/env python3
"""
Test Didomi CMP consent on Denik.cz (Vltava Labe Media).
Unlike Zive, Denik's Didomi banner appears to be standard and visible.
"""

import asyncio
from playwright.async_api import async_playwright

async def click_denik_consent():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="cs-CZ",
        )
        page = await context.new_page()
        
        print("\n" + "="*60)
        print("Testing: https://www.denik.cz")
        print("="*60)
        
        print("1. Navigating...")
        await page.goto("https://www.denik.cz", wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)  # Site can be slow
        
        # Check for Didomi
        has_didomi = await page.evaluate("() => !!window.Didomi")
        print(f"2. Has Didomi: {has_didomi}")
        
        # Check if banner is visible
        print("3. Checking for banner visibility...")
        try:
            # Denik uses .didomi-popup-container or #didomi-notice
            banner = page.locator(".didomi-popup-container, #didomi-notice")
            if await banner.count() > 0 and await banner.first.is_visible():
                print("   Banner detected and visible!")
                
                # Click Accept
                print("4. Clicking 'Souhlasím'...")
                # Try ID first
                try:
                    await page.click("#didomi-notice-agree-button", timeout=3000)
                    print("   ✅ Clicked #didomi-notice-agree-button")
                except:
                    # Fallback to text
                    await page.get_by_text("Souhlasím", exact=True).click()
                    print("   ✅ Clicked 'Souhlasím' by text")
                
                await page.wait_for_timeout(3000)
                
                # Verify it's gone
                if not await banner.first.is_visible():
                    print("   ✅ Banner is gone!")
                    
                    # Check for OneSignal prompt (often appears after)
                    onesignal = page.locator("#onesignal-slidedown-allow-button")
                    if await onesignal.count() > 0 and await onesignal.is_visible():
                        print("   ℹ️  OneSignal prompt appeared (ignoring for Consent test)")
                    
                    # Verify cookie
                    has_cookie = await page.evaluate("document.cookie.includes('euconsent-v2')")
                    print(f"   Cookie 'euconsent-v2' present: {has_cookie}")
                else:
                    print("   ❌ Banner still visible after click")
            else:
                print("   ❌ Banner not found or not visible")
                # Debug info
                html_sample = await page.evaluate("document.body.innerHTML.substring(0, 500)")
                print(f"   Body sample: {html_sample}...")
                
        except Exception as e:
            print(f"   ❌ Error searching/clicking banner: {e}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(click_denik_consent())
