#!/usr/bin/env python3
"""
Test Economia & Allegro Sites.
- Economia (Aktualne.cz): Standard Didomi
- Allegro Group (Mall.cz, CZC.cz): Custom Allegro GDPR Plugin
"""

import asyncio
from playwright.async_api import async_playwright

async def test_economia_didomi():
    print("\n" + "="*60)
    print("Testing Economia: https://www.aktualne.cz")
    print("="*60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(locale="cs-CZ")
        page = await context.new_page()
        
        await page.goto("https://www.aktualne.cz")
        await page.wait_for_timeout(3000)
        
        try:
            # Standard Didomi
            btn = page.locator("#didomi-notice-agree-button")
            if await btn.count() > 0:
                await btn.click()
                print("   ✅ Clicked #didomi-notice-agree-button")
                await page.wait_for_timeout(2000)
                if not await btn.is_visible():
                    print("   ✅ Banner dismissed")
            else:
                print("   ❌ Didomi button not found")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            
        await browser.close()


async def test_allegro_sites(url):
    print("\n" + "="*60)
    print(f"Testing Allegro Group: {url}")
    print("="*60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(locale="cs-CZ")
        page = await context.new_page()
        
        await page.goto(url)
        await page.wait_for_timeout(4000)
        
        try:
            # Allegro custom data-testid
            # Selector: button[data-testid="accept_home_view_action"]
            btn = page.locator('button[data-testid="accept_home_view_action"]')
            
            if await btn.count() > 0:
                # Might need to close informational modal first? 
                # Subagent didn't need to, but explicit wait is good.
                if await btn.is_visible():
                    await btn.click()
                    print("   ✅ Clicked [data-testid='accept_home_view_action']")
                    await page.wait_for_timeout(2000)
                    if not await btn.is_visible():
                        print("   ✅ Banner dismissed")
                else:
                     print("   ⚠️  Button found but not visible (obscured?)")
                     # Try force click
                     await btn.click(force=True)
                     print("   ✅ Force clicked")
            else:
                print("   ❌ Allegro button not found")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
            
        await browser.close()

async def run_all():
    await test_economia_didomi()
    await test_allegro_sites("https://www.mall.cz")
    await test_allegro_sites("https://www.czc.cz")

if __name__ == "__main__":
    asyncio.run(run_all())
