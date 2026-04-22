import httpx
import re
from models.job import Job, JobSource
from searchers.base import BaseSearcher
from config.settings import settings
from loguru import logger

ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/1"
MAX_JOBS = 20


class AdzunaSearcher(BaseSearcher):
    """Adzuna UK job board — uses free public API (app_id/app_key optional)."""

    async def login(self) -> bool:
        return True

    async def search(self, query: str, location: str = "United Kingdom") -> list[Job]:
        params: dict = {
            "results_per_page": MAX_JOBS,
            "what": query,
            "content-type": "application/json",
            "sort_by": "date",
            "max_days_old": 7,
        }

        app_id = getattr(settings, "adzuna_app_id", None)
        app_key = getattr(settings, "adzuna_app_key", None)
        if app_id and app_key:
            params["app_id"] = app_id
            params["app_key"] = app_key
        else:
            logger.warning("Adzuna: no API credentials — falling back to browser scrape")
            return await self._browser_search(query)

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(ADZUNA_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"Adzuna API error: {e}")
            return await self._browser_search(query)

        jobs = []
        for item in data.get("results", []):
            title = item.get("title", "")
            company = item.get("company", {}).get("display_name", "Unknown")
            loc = item.get("location", {}).get("display_name", "United Kingdom")
            url = item.get("redirect_url", "")
            description = item.get("description", "")
            sal_min = item.get("salary_min")
            sal_max = item.get("salary_max")

            jobs.append(Job(
                title=title,
                company=company,
                location=loc,
                url=url.split("?")[0] if url else "",
                source=JobSource.ADZUNA,
                description=description[:2000],
                salary_min=int(sal_min) if sal_min else None,
                salary_max=int(sal_max) if sal_max else None,
                is_remote="remote" in loc.lower() or "remote" in description.lower(),
                easy_apply=False,
                external_apply_url=url,
            ))

        logger.info(f"Adzuna: found {len(jobs)} jobs")
        return jobs

    async def _browser_search(self, query: str) -> list[Job]:
        """Fallback: scrape Adzuna UK search page."""
        url = (
            f"https://www.adzuna.co.uk/search?q={query.replace(' ', '+')}"
            f"&w=United+Kingdom&days_old=7&sort=date"
        )
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(3, 5)
        except Exception as e:
            logger.error(f"Adzuna: navigation error: {e}")
            return []

        await self._dismiss_consent()

        jobs = []
        try:
            await self.page.wait_for_selector('[data-cy="result"]', timeout=12000)
            await self.scroll_naturally()

            cards = await self.page.locator('[data-cy="result"]').all()
            cards = cards[:MAX_JOBS]

            for card in cards:
                try:
                    title_el = card.locator('h2 a').first
                    title = await self.safe_inner_text(title_el)
                    href = await self.safe_get_attribute(title_el, "href")

                    company = await self.safe_inner_text(card.locator('[data-cy="company"]').first)
                    loc_text = await self.safe_inner_text(card.locator('[data-cy="location"]').first)
                    description = await self.safe_inner_text(card.locator('[data-cy="snippet"]').first)

                    if not title or not href:
                        continue

                    clean_url = href.split("?")[0]
                    jobs.append(Job(
                        title=title,
                        company=company or "Unknown",
                        location=loc_text or "United Kingdom",
                        url=clean_url,
                        source=JobSource.ADZUNA,
                        description=description,
                        is_remote="remote" in loc_text.lower(),
                        easy_apply=False,
                        external_apply_url=clean_url,
                    ))
                    await self.human_delay(0.2, 0.5)
                except Exception as e:
                    logger.debug(f"Adzuna: skipped card: {e}")

        except Exception as e:
            logger.error(f"Adzuna: scrape error: {e}")

        logger.info(f"Adzuna: found {len(jobs)} jobs (browser)")
        return jobs

    async def _dismiss_consent(self) -> None:
        for sel in [
            'button:has-text("Accept all")',
            'button:has-text("Accept All")',
            'button:has-text("Accept")',
            '#onetrust-accept-btn-handler',
            '[data-cy="cookie-consent-accept"]',
        ]:
            try:
                btn = self.page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click()
                    await self.human_delay(1, 2)
                    return
            except Exception:
                pass

    async def apply(self, job: Job, cover_letter: str, resume_path: str) -> bool:
        """Navigate to Adzuna job and apply on the employer's site."""
        target_url = job.external_apply_url or job.url
        if not target_url:
            return False

        try:
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(2, 4)
            await self._dismiss_consent()

            # Try to find "Apply" button which may open external site
            for sel in [
                'a[data-cy="apply-button"]',
                'button[data-cy="apply-button"]',
                'a:has-text("Apply now")',
                'button:has-text("Apply now")',
            ]:
                try:
                    btn = self.page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                        try:
                            async with self.page.context.expect_page() as new_page_info:
                                await btn.click()
                            new_page = await new_page_info.value
                            await new_page.wait_for_load_state("domcontentloaded", timeout=20000)
                            await self.human_delay(2, 4)
                            result = await self._fill_form(new_page, cover_letter, resume_path)
                            await new_page.close()
                            return result
                        except Exception:
                            await btn.click()
                            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
                            await self.human_delay(2, 4)
                            return await self._fill_form(self.page, cover_letter, resume_path)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Adzuna: apply error for {job.title}: {e}")
        return False

    async def _fill_form(self, page, cover_letter: str, resume_path: str) -> bool:
        try:
            fi = page.locator('input[type="file"]').first
            if await fi.count() > 0 and resume_path:
                await fi.set_input_files(resume_path)
                await self.human_delay(1, 2)
        except Exception:
            pass

        try:
            for ta in await page.locator("textarea").all():
                placeholder = (await ta.get_attribute("placeholder") or "").lower()
                label = (await ta.get_attribute("aria-label") or "").lower()
                if any(k in placeholder or k in label for k in ["cover", "letter", "message"]):
                    await ta.fill(cover_letter)
                    await self.human_delay(0.5, 1)
                    break
        except Exception:
            pass

        for sel in ['button[type="submit"]', 'input[type="submit"]', 'button:has-text("Submit")', 'button:has-text("Apply")']:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await btn.click()
                    await self.human_delay(2, 4)
                    return True
            except Exception:
                pass
        return False
