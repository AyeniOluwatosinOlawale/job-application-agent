import re
from searchers.base import BaseSearcher
from models.job import Job, JobSource
from loguru import logger

REED_SEARCH_URL = (
    "https://www.reed.co.uk/jobs/ai-engineer-jobs"
    "?keywords={query}"
    "&location=united+kingdom"
    "&datecreatedoffset=3"   # last 3 days
    "&sortby=displaydate"
)
MAX_JOBS = 15


class ReedSearcher(BaseSearcher):

    async def login(self) -> bool:
        return True  # no login required for search

    async def search(self, query: str, location: str = "United Kingdom") -> list[Job]:
        url = REED_SEARCH_URL.format(query=query.replace(" ", "+"))
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(3, 5)
        except Exception as e:
            logger.error(f"Reed: navigation error: {e}")
            return []

        await self._dismiss_consent()

        jobs = []
        try:
            await self.page.wait_for_selector("[data-qa='job-card']", timeout=12000)
            await self.scroll_naturally()

            cards = await self.page.locator("[data-qa='job-card']").all()
            cards = cards[:MAX_JOBS]

            for card in cards:
                try:
                    title = await self.safe_inner_text(
                        card.locator("[data-qa='job-card-title']").first
                    )
                    if not title:
                        title = await self.safe_inner_text(
                            card.locator("[data-qa='job-title-btn-wrapper']").first
                        )

                    # Company is embedded in "11 March by Adria Solutions"
                    posted_by = await self.safe_inner_text(
                        card.locator("[data-qa='job-posted-by']").first
                    )
                    company = ""
                    if " by " in posted_by:
                        company = posted_by.split(" by ", 1)[1].strip()

                    location_text = await self.safe_inner_text(
                        card.locator("[data-qa='job-metadata-location']").first
                    )

                    salary = await self.safe_inner_text(
                        card.locator("[data-qa='job-metadata-salary']").first
                    )

                    # Easy Apply badge
                    easy_apply = await card.locator("[data-qa*='easyApply']").count() > 0

                    # Job URL — find link to job detail page
                    data_id = await card.get_attribute("data-id") or ""
                    job_id_num = data_id.replace("job", "").strip()

                    link_el = card.locator("a[href*='/jobs/'][href*='source=searchResults']").first
                    href = await self.safe_get_attribute(link_el, "href")
                    if not href and job_id_num:
                        slug = re.sub(r"\s+", "-", title.lower())
                        slug = re.sub(r"[^a-z0-9-]", "", slug)[:60]
                        href = f"https://www.reed.co.uk/jobs/{slug}/{job_id_num}"

                    if not title or not href:
                        continue

                    if not href.startswith("http"):
                        href = "https://www.reed.co.uk" + href
                    clean_url = href.split("?")[0]

                    jobs.append(Job(
                        title=title,
                        company=company or "Unknown",
                        location=location_text or "United Kingdom",
                        url=clean_url,
                        source=JobSource.REED,
                        is_remote="remote" in location_text.lower(),
                        easy_apply=easy_apply,
                        external_apply_url=clean_url,
                    ))
                    await self.human_delay(0.3, 0.7)
                except Exception as e:
                    logger.debug(f"Reed: skipped card: {e}")

        except Exception as e:
            logger.error(f"Reed: parsing error: {e}")

        logger.info(f"Reed: found {len(jobs)} jobs")
        return jobs

    async def _dismiss_consent(self) -> None:
        for sel in [
            'button:has-text("Accept all")',
            'button:has-text("Accept cookies")',
            'button:has-text("Accept")',
            '#onetrust-accept-btn-handler',
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
        """Navigate to Reed job page and apply via Easy Apply or external link."""
        try:
            await self.page.goto(job.url, wait_until="domcontentloaded", timeout=60000)
            await self.human_delay(2, 4)
            await self._dismiss_consent()

            # Try Easy Apply button on Reed (opens Reed's own application modal)
            for sel in [
                'button[data-qa="applyJobBtn"]',
                'a[data-qa="applyJobBtn"]',
                'button:has-text("Easy apply")',
                'button:has-text("Apply now")',
                'a:has-text("Apply now")',
            ]:
                try:
                    btn = self.page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                        btn_text = (await self.safe_inner_text(btn)).lower()
                        logger.info(f"Reed: apply button found: '{btn_text}' for {job.title}")

                        # Check if it opens a new tab or navigates
                        try:
                            async with self.page.context.expect_page() as new_page_info:
                                await btn.click()
                            new_page = await new_page_info.value
                            await new_page.wait_for_load_state("domcontentloaded", timeout=20000)
                            await self.human_delay(2, 4)
                            result = await self._apply_on_page(new_page, cover_letter, resume_path)
                            await new_page.close()
                            return result
                        except Exception:
                            await btn.click()
                            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
                            await self.human_delay(2, 4)
                            return await self._apply_on_page(self.page, cover_letter, resume_path)
                except Exception:
                    pass

            logger.info(f"Reed: no apply button found for '{job.title}'")
        except Exception as e:
            logger.error(f"Reed: apply error for {job.title}: {e}")
        return False

    async def _apply_on_page(self, page, cover_letter: str, resume_path: str) -> bool:
        """Fill a generic ATS or Reed application form."""
        try:
            file_input = page.locator('input[type="file"]').first
            if await file_input.count() > 0 and resume_path:
                await file_input.set_input_files(resume_path)
                await self.human_delay(1, 2)
        except Exception as e:
            logger.debug(f"Reed: resume upload failed: {e}")

        try:
            for ta in await page.locator("textarea").all():
                placeholder = (await ta.get_attribute("placeholder") or "").lower()
                label = (await ta.get_attribute("aria-label") or "").lower()
                if any(k in placeholder or k in label for k in ["cover", "letter", "message", "intro"]):
                    await ta.fill(cover_letter)
                    await self.human_delay(0.5, 1)
                    break
        except Exception as e:
            logger.debug(f"Reed: cover letter failed: {e}")

        for sel in [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Submit")',
            'button:has-text("Apply")',
            'button:has-text("Send application")',
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await btn.click()
                    await self.human_delay(2, 4)
                    logger.info("Reed: application submitted")
                    return True
            except Exception:
                pass

        return False
