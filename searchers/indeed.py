from searchers.base import BaseSearcher
from models.job import Job, JobSource
from config.settings import settings
from loguru import logger
import asyncio

INDEED_SEARCH_URL = "https://www.indeed.com/jobs?q={query}&l={location}&fromage=1&sort=date"
INDEED_LOGIN_URL = "https://secure.indeed.com/auth"


class IndeedSearcher(BaseSearcher):

    async def login(self) -> bool:
        if not settings.indeed_email or not settings.indeed_password:
            logger.info("Indeed: no credentials provided, searching anonymously")
            return True

        try:
            await self.page.goto(INDEED_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(1.5, 3)

            email_field = self.page.locator('input[type="email"], input[name="email"]').first
            if await email_field.count() > 0:
                await self.human_type(email_field, settings.indeed_email)
                await self.human_delay(0.5, 1)

                continue_btn = self.page.locator('button[type="submit"]').first
                await continue_btn.click()
                await self.human_delay(1, 2)

            pw_field = self.page.locator('input[type="password"]').first
            if await pw_field.count() > 0:
                await self.human_type(pw_field, settings.indeed_password)
                await self.human_delay(0.5, 1)
                await self.page.locator('button[type="submit"]').first.click()
                await self.page.wait_for_load_state("networkidle", timeout=15000)

            logged_in = "dashboard" in self.page.url or "indeed.com" in self.page.url
            logger.info(f"Indeed: login {'success' if logged_in else 'uncertain'}")
            return logged_in
        except Exception as e:
            logger.warning(f"Indeed: login error: {e}")
            return True  # Proceed anyway — search works without login

    async def search(self, query: str, location: str = "Remote") -> list[Job]:
        url = INDEED_SEARCH_URL.format(
            query=query.replace(" ", "+"),
            location=location.replace(" ", "+"),
        )
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(2, 4)
            await self.scroll_naturally()
        except Exception as e:
            logger.error(f"Indeed: navigation error: {e}")
            return []

        jobs = []
        try:
            cards = await self.page.locator('[data-jk]').all()
            cards = cards[:20]

            for card in cards:
                try:
                    title_el = card.locator('[class*="jobTitle"] a, h2 a').first
                    title = await self.safe_inner_text(title_el)
                    if not title:
                        continue

                    company = await self.safe_inner_text(card.locator('[data-testid="company-name"]').first)
                    location_text = await self.safe_inner_text(card.locator('[data-testid="text-location"]').first)
                    job_key = await card.get_attribute("data-jk") or ""

                    if not job_key:
                        continue

                    jobs.append(Job(
                        title=title,
                        company=company or "Unknown",
                        location=location_text or location,
                        url=f"https://www.indeed.com/viewjob?jk={job_key}",
                        source=JobSource.INDEED,
                        is_remote="remote" in location_text.lower(),
                        easy_apply=True,
                    ))
                    await self.human_delay(0.3, 0.8)
                except Exception as e:
                    logger.debug(f"Indeed: skipped card: {e}")

        except Exception as e:
            logger.error(f"Indeed: card parsing error: {e}")

        logger.info(f"Indeed: found {len(jobs)} jobs")
        return jobs

    async def apply(self, job: Job, cover_letter: str, resume_path: str) -> bool:
        try:
            await self.page.goto(job.url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(2, 4)

            # Click the Indeed Apply button (opens a popup or redirects)
            apply_btn = self.page.locator('#indeedApplyButton, [data-testid="indeedApplyButton"], button:has-text("Apply now")').first
            if await apply_btn.count() == 0 or not await apply_btn.is_visible():
                logger.info(f"Indeed: no apply button found for {job.title}")
                return False

            # Handle potential popup
            try:
                async with self.page.expect_popup(timeout=5000) as popup_info:
                    await apply_btn.click()
                popup = await popup_info.value
                await popup.wait_for_load_state("domcontentloaded")
                page = popup
            except Exception:
                await apply_btn.click()
                await self.human_delay(2, 3)
                page = self.page

            # Multi-step form loop
            for step in range(8):
                await self.human_delay(1.5, 3)

                # Upload resume
                resume_input = page.locator('input[type="file"]').first
                if await resume_input.count() > 0 and resume_path:
                    try:
                        await resume_input.set_input_files(resume_path)
                        await self.human_delay(1, 2)
                    except Exception:
                        pass

                # Fill cover letter
                cl_field = page.locator('textarea[id*="cover"], textarea[name*="cover"]').first
                if await cl_field.count() > 0 and cover_letter:
                    await cl_field.fill(cover_letter)

                # Check for submit
                submit = page.locator('button:has-text("Submit"), button[type="submit"]:has-text("Submit")').first
                if await submit.count() > 0 and await submit.is_visible():
                    await submit.click()
                    await self.human_delay(2, 4)
                    logger.info(f"Indeed: submitted application for {job.title} at {job.company}")
                    return True

                # Click Continue/Next
                next_btn = page.locator('button:has-text("Continue"), button:has-text("Next")').first
                if await next_btn.count() > 0 and await next_btn.is_visible():
                    await next_btn.click()
                else:
                    break

        except Exception as e:
            logger.error(f"Indeed: apply error for {job.title}: {e}")

        return False
