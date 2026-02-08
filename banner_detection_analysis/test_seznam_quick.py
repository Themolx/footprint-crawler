#!/usr/bin/env python3
"""Quick test for Seznam consent banner."""

import asyncio
from playwright.async_api import async_playwright


async def test_seznam():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="cs-CZ",
        )
        page = await context.new_page()
        
        print("1. Navigating to seznam.cz...")
        await page.goto("https://www.seznam.cz", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        print("2. Taking screenshot BEFORE click...")
        await page.screenshot(path="before_click.png")
        
        print("3. Clicking initial banner via Shadow DOM...")
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
        print(f"   Initial click result: {clicked}")
        
        await page.wait_for_timeout(3000)
        print(f"4. Current URL: {page.url}")
        
        if "cmp.seznam.cz" in page.url:
            print("5. On CMP page! Taking screenshot...")
            await page.screenshot(path="cmp_page.png")
            
            print("6. Trying to click 'Souhlasím' button...")
            
            # Try get_by_text (Playwright can pierce some shadow DOM)
            try:
                btn = page.get_by_text("Souhlasím", exact=True)
                count = await btn.count()
                print(f"   Found {count} 'Souhlasím' buttons via get_by_text")
                if count > 0:
                    await btn.first.click(timeout=5000)
                    print("   CLICKED via get_by_text!")
            except Exception as e:
                print(f"   get_by_text failed: {e}")
            
            await page.wait_for_timeout(2000)
            print(f"7. Final URL: {page.url}")
            await page.screenshot(path="after_click.png")
        
        print("\nDone! Check before_click.png, cmp_page.png, after_click.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_seznam())
