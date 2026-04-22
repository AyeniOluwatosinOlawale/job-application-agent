import httpx
from models.job import Job, JobSource
from searchers.base import BaseSearcher
from loguru import logger

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSearcher(BaseSearcher):
    """Pure HTTP searcher — no browser needed for search. Browser only for apply."""

    async def login(self) -> bool:
        return True  # Public API, no auth

    async def search(self, query: str, location: str = "Remote") -> list[Job]:
        params = {
            "category": "software-dev",
            "search": query,
            "limit": 50,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(REMOTIVE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"Remotive API error: {e}")
            return []

        jobs = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            if not any(kw in title.lower() for kw in ["ai", "ml", "machine learning", "engineer", "nlp", "llm"]):
                continue

            loc = item.get("candidate_required_location") or "Remote"
            salary = item.get("salary") or ""
            sal_min, sal_max = self._parse_salary(salary)

            jobs.append(Job(
                title=title,
                company=item.get("company_name", ""),
                location=loc,
                url=item.get("url", ""),
                source=JobSource.REMOTIVE,
                description=item.get("description", "")[:2000],
                salary_min=sal_min,
                salary_max=sal_max,
                is_remote=True,
                easy_apply=False,
                external_apply_url=item.get("url", ""),
            ))

        logger.info(f"Remotive: found {len(jobs)} matching jobs")
        return jobs

    async def apply(self, job: Job, cover_letter: str, resume_path: str) -> bool:
        """
        Remotive jobs link to external company sites. Navigate to the apply URL
        and attempt to fill any standard application form fields.
        """
        target_url = job.external_apply_url or job.url
        if not target_url:
            return False

        try:
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(2, 4)

            # Dismiss cookie consent
            for selector in ['button:has-text("Accept all")', 'button:has-text("Accept")', 'button:has-text("Agree")', '.fc-button-label']:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.count() > 0 and await btn.is_visible(timeout=1500):
                        await btn.click()
                        await self.human_delay(0.5, 1)
                        break
                except Exception:
                    pass

            # Upload resume if a file input exists
            file_inputs = await self.page.locator('input[type="file"]').all()
            if file_inputs and resume_path:
                await file_inputs[0].set_input_files(resume_path)
                await self.human_delay(1, 2)

            # Fill cover letter if textarea present
            textareas = await self.page.locator("textarea").all()
            for ta in textareas:
                placeholder = (await ta.get_attribute("placeholder") or "").lower()
                label_text = (await ta.get_attribute("aria-label") or "").lower()
                if "cover" in placeholder or "cover" in label_text or "letter" in placeholder:
                    await ta.fill(cover_letter)
                    await self.human_delay(0.5, 1)
                    break

            # Look for submit button
            for selector in ['button[type="submit"]', 'input[type="submit"]', 'button:has-text("Submit")', 'button:has-text("Apply")']:
                btn = self.page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await self.human_delay(2, 4)
                    return True

        except Exception as e:
            logger.warning(f"Remotive apply failed for {job.url}: {e}")

        return False

    @staticmethod
    def _parse_salary(salary_str: str) -> tuple[int | None, int | None]:
        import re
        nums = re.findall(r"\d[\d,]*", salary_str.replace(",", ""))
        cleaned = [int(n.replace(",", "")) for n in nums if int(n.replace(",", "")) > 1000]
        if len(cleaned) >= 2:
            return min(cleaned), max(cleaned)
        if len(cleaned) == 1:
            return cleaned[0], None
        return None, None
