from abc import ABC, abstractmethod
from playwright.async_api import Browser, BrowserContext, Page
from models.job import Job
from config.settings import settings
from loguru import logger
import asyncio
import random


class BaseSearcher(ABC):
    def __init__(self, browser: Browser):
        self.browser = browser
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def setup(self) -> None:
        self.context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York",
        )
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = { runtime: {} };
        """)
        self.page = await self.context.new_page()

    async def human_delay(self, min_s: float | None = None, max_s: float | None = None) -> None:
        lo = min_s if min_s is not None else settings.min_delay_seconds
        hi = max_s if max_s is not None else settings.max_delay_seconds
        await asyncio.sleep(random.uniform(lo, hi))

    async def human_type(self, locator, text: str) -> None:
        await locator.click()
        await asyncio.sleep(random.uniform(0.3, 0.7))
        for char in text:
            await locator.type(char, delay=random.randint(60, 180))

    async def scroll_naturally(self, page: Page | None = None) -> None:
        p = page or self.page
        height = await p.evaluate("document.body.scrollHeight")
        current = 0
        while current < height:
            scroll_amount = random.randint(200, 500)
            current += scroll_amount
            await p.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(random.uniform(0.3, 1.0))

    async def safe_inner_text(self, locator, default: str = "") -> str:
        try:
            return (await locator.inner_text(timeout=3000)).strip()
        except Exception:
            return default

    async def safe_get_attribute(self, locator, attr: str, default: str = "") -> str:
        try:
            val = await locator.get_attribute(attr, timeout=3000)
            return val or default
        except Exception:
            return default

    @abstractmethod
    async def login(self) -> bool: ...

    @abstractmethod
    async def search(self, query: str, location: str) -> list[Job]: ...

    @abstractmethod
    async def apply(self, job: Job, cover_letter: str, resume_path: str) -> bool: ...

    async def teardown(self) -> None:
        try:
            if self.context:
                await self.context.close()
        except Exception as e:
            logger.warning(f"Teardown error: {e}")
