from searchers.base import BaseSearcher
from models.job import Job, JobSource
from loguru import logger

TOTALJOBS_URL = (
    "https://www.totaljobs.com/jobs/ai-engineer"
    "?keywords={query}"
    "&location=United+Kingdom"
    "&postedWithin=7"
    "&sort=date"
)
MAX_JOBS = 15


class TotaljobsSearcher(BaseSearcher):

    async def login(self) -> bool:
        return True

    async def search(self, query: str, location: str = "United Kingdom") -> list[Job]:
        url = TOTALJOBS_URL.format(query=query.replace(" ", "+"))
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(3, 5)
        except Exception as e:
            logger.error(f"Totaljobs: navigation error: {e}")
            return []

        await self._dismiss_consent()

        jobs = []
        try:
            # Totaljobs uses article tags for job cards
            await self.page.wait_for_selector("article.job-result, [data-testid='job-result']", timeout=12000)
            await self.scroll_naturally()

            cards = await self.page.locator("article.job-result, [data-testid='job-result']").all()
            cards = cards[:MAX_JOBS]

            for card in cards:
                try:
                    title_el = card.locator("h2 a, h3 a, .job-result__title a, [data-testid='job-title'] a").first
                    title = await self.safe_inner_text(title_el)
                    href = await self.safe_get_attribute(title_el, "href")

                    company = await self.safe_inner_text(
                        card.locator(".job-result__company-name, [data-testid='company-name']").first
                    )
                    loc_text = await self.safe_inner_text(
                        card.locator(".job-result__location, [data-testid='job-location']").first
                    )
                    description = await self.safe_inner_text(
                        card.locator(".job-result__description, [data-testid='job-description']").first
                    )

                    if not title or not href:
                        continue

                    if not href.startswith("http"):
                        href = "https://www.totaljobs.com" + href
                    clean_url = href.split("?")[0]

                    jobs.append(Job(
                        title=title,
                        company=company or "Unknown",
                        location=loc_text or "United Kingdom",
                        url=clean_url,
                        source=JobSource.TOTALJOBS,
                        description=description,
                        is_remote="remote" in loc_text.lower(),
                        easy_apply=False,
                        external_apply_url=clean_url,
                    ))
                    await self.human_delay(0.2, 0.5)
                except Exception as e:
                    logger.debug(f"Totaljobs: skipped card: {e}")

        except Exception as e:
            logger.error(f"Totaljobs: scrape error: {e}")

        logger.info(f"Totaljobs: found {len(jobs)} jobs")
        return jobs

    async def _dismiss_consent(self) -> None:
        for sel in [
            'button:has-text("Accept all")',
            'button:has-text("Accept All")',
            'button:has-text("Accept")',
            '#onetrust-accept-btn-handler',
            '[aria-label="Accept all cookies"]',
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
        try:
            await self.page.goto(job.url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(2, 4)
            await self._dismiss_consent()

            for sel in [
                'a:has-text("Apply now")',
                'button:has-text("Apply now")',
                '[data-testid="apply-button"]',
                'a:has-text("Apply")',
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
            logger.error(f"Totaljobs: apply error for {job.title}: {e}")
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
