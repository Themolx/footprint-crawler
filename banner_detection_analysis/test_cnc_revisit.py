#!/usr/bin/env python3
"""
Re-test CNC sites (Blesk.cz) with enhanced debugging.
CNC uses Didomi but previous tests failed to find the banner.
Possible reasons:
- Banner is in an iframe?
- Banner is hidden by default (Opt-out model?) -> Unlikely for GDPR.
- Specific anti-bot protection hiding the banner?
"""

import asyncio
from playwright.async_api import async_playwright

async def test_blesk_enhanced():
    print("\n" + "="*60)
    print("Testing CNC: https://www.blesk.cz")
    print("="*60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="cs-CZ",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        # Enable console logging
        page.on("console", lambda msg: print(f"BROWSER CONSOLE: {msg.text}"))
        
        print("1. Navigating...")
        await page.goto("https://www.blesk.cz", wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        
        # Check Didomi status
        didomi_ready = await page.evaluate("window.Didomi && window.Didomi.isReady()")
        print(f"2. Didomi Ready: {didomi_ready}")
        
        # Try to force show
        if didomi_ready:
            print("   Forcing Didomi.notice.show()...")
            await page.evaluate("window.Didomi.notice.show()")
            await page.wait_for_timeout(2000)
            
        # Debug HTML structure
        print("3. Searching for #didomi-host...")
        host = page.locator("#didomi-host")
        if await host.count() > 0:
            print("   Found #didomi-host!")
            # Check visibility
            box = await host.bounding_box()
            print(f"   Bounding box: {box}")
            
            # Check inner HTML
            inner = await host.inner_html()
            print(f"   Inner HTML length: {len(inner)}")
            if len(inner) < 100:
                print(f"   Inner HTML content: {inner}")
        else:
            print("   ❌ #didomi-host NOT found")
            
        # Check iframes
        frames = page.frames
        print(f"4. Found {len(frames)} frames")
        for f in frames:
            if "didomi" in f.url:
                print(f"   Didomi frame found: {f.url}")
                
        # Try finding button by text
        print("5. Searching for 'Souhlasím' text...")
        btn = page.get_by_text("Souhlasím", exact=True)
        if await btn.count() > 0:
            print("   Found button by text!")
            await btn.click()
            print("   ✅ Clicked via Text")
        else:
             print("   ❌ Text 'Souhlasím' not found")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_blesk_enhanced())
