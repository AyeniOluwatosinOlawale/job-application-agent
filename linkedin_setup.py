"""
Run this once to save your LinkedIn session.
The agent will reuse it automatically on every run.

Usage:
    .venv/bin/python linkedin_setup.py
"""
import asyncio
import os
from playwright.async_api import async_playwright

PROFILE_DIR = os.path.abspath(".linkedin_profile")


async def main():
    print("\n=== LinkedIn Session Setup ===")
    print(f"Profile will be saved to: {PROFILE_DIR}")
    print("\nA browser window will open.")
    print("Log in to LinkedIn. Complete any 2FA if prompted.")
    print("The script saves your session automatically once you reach your feed.\n")

    os.makedirs(PROFILE_DIR, exist_ok=True)

    async with async_playwright() as pw:
        # Persistent context stores cookies/session to disk automatically
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

        page = context.pages[0] if context.pages else await context.new_page()

        # Check if already logged in
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        from urllib.parse import urlparse
        parsed = urlparse(page.url)
        if parsed.netloc == "www.linkedin.com" and parsed.path.startswith("/feed"):
            print("✓ Already logged in! Session is ready.\n")
            await context.close()
            return

        # Not logged in — go to login page
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
        print("Please log in now. You have 5 minutes...")

        # Wait up to 5 minutes for user to log in and land on feed
        try:
            await page.wait_for_url(
                lambda url: any(p in url for p in ["/feed", "/mynetwork", "/jobs", "/in/"]),
                timeout=300000,  # 5 minutes
            )
            # Give session a moment to fully establish
            await asyncio.sleep(3)
            print(f"\n✓ Logged in! Session saved to {PROFILE_DIR}")
            print("Run the agent now — LinkedIn applications are enabled.\n")
        except Exception:
            print("\n✗ Timed out. Please re-run the script and log in within 5 minutes.\n")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
