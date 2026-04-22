import httpx
from models.job import Job, JobSource
from searchers.base import BaseSearcher
from loguru import logger

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowSearcher(BaseSearcher):
    """Pure HTTP searcher — no browser needed for search. Browser only for apply."""

    async def login(self) -> bool:
        return True  # Public API, no auth

    async def search(self, query: str, location: str = "Remote") -> list[Job]:
        params = {"search": query}
        if "remote" in location.lower():
            params["remote"] = "true"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(ARBEITNOW_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"Arbeitnow API error: {e}")
            return []

        jobs = []
        for item in data.get("data", []):
            title = item.get("title", "")
            loc = item.get("location") or "Remote"
            is_remote = item.get("remote", False)

            jobs.append(Job(
                title=title,
                company=item.get("company_name", ""),
                location=loc,
                url=item.get("url", ""),
                source=JobSource.ARBEITNOW,
                description=item.get("description", "")[:2000],
                is_remote=is_remote,
                easy_apply=False,
                external_apply_url=item.get("url", ""),
            ))

        logger.info(f"Arbeitnow: found {len(jobs)} matching jobs")
        return jobs

    async def _dismiss_cookie_consent(self) -> None:
        """Dismiss any cookie/consent overlays that block clicks."""
        # Try standard button clicks first
        for selector in [
            'button:has-text("Accept all")',
            'button:has-text("Accept All")',
            'button:has-text("Accept")',
            'button:has-text("Agree")',
            'button:has-text("Consent")',
            '[aria-label*="accept" i]',
        ]:
            try:
                btn = self.page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=1500):
                    await btn.click()
                    await self.human_delay(0.5, 1)
                    return
            except Exception:
                pass

        # Funding Choices overlay — remove via JavaScript if buttons are blocked
        try:
            removed = await self.page.evaluate("""
                () => {
                    const root = document.querySelector('.fc-consent-root');
                    if (root) { root.remove(); return true; }
                    const overlay = document.querySelector('.fc-dialog-overlay');
                    if (overlay) { overlay.remove(); return true; }
                    return false;
                }
            """)
            if removed:
                await self.human_delay(0.3, 0.7)
        except Exception:
            pass

    async def apply(self, job: Job, cover_letter: str, resume_path: str) -> bool:
        """Navigate to the external apply URL and fill standard form fields."""
        target_url = job.external_apply_url or job.url
        if not target_url:
            return False

        try:
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(2, 4)
            await self._dismiss_cookie_consent()

            # Upload resume
            file_inputs = await self.page.locator('input[type="file"]').all()
            if file_inputs and resume_path:
                await file_inputs[0].set_input_files(resume_path)
                await self.human_delay(1, 2)

            # Cover letter
            textareas = await self.page.locator("textarea").all()
            for ta in textareas:
                placeholder = (await ta.get_attribute("placeholder") or "").lower()
                if "cover" in placeholder or "letter" in placeholder or "message" in placeholder:
                    await ta.fill(cover_letter)
                    await self.human_delay(0.5, 1)
                    break

            # Submit
            for selector in ['button[type="submit"]', 'input[type="submit"]', 'button:has-text("Apply")', 'button:has-text("Submit")']:
                btn = self.page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await self.human_delay(2, 4)
                    return True

        except Exception as e:
            logger.warning(f"Arbeitnow apply failed for {job.url}: {e}")

        return False
