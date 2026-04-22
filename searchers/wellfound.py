from searchers.base import BaseSearcher
from models.job import Job, JobSource
from config.settings import settings
from loguru import logger

WELLFOUND_SEARCH_URL = "https://wellfound.com/role/r/ai-engineer"
WELLFOUND_LOGIN_URL = "https://wellfound.com/login"


class WellfoundSearcher(BaseSearcher):

    async def login(self) -> bool:
        if not settings.wellfound_email or not settings.wellfound_password:
            logger.info("Wellfound: no credentials provided, skipping login")
            return False

        try:
            await self.page.goto(WELLFOUND_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(1.5, 3)

            email_field = self.page.locator('input[name="user[email]"], input[type="email"]').first
            pw_field = self.page.locator('input[name="user[password]"], input[type="password"]').first

            if await email_field.count() > 0:
                await self.human_type(email_field, settings.wellfound_email)
            if await pw_field.count() > 0:
                await self.human_type(pw_field, settings.wellfound_password)

            await self.human_delay(0.5, 1)
            submit = self.page.locator('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")').first
            await submit.click()
            await self.page.wait_for_load_state("networkidle", timeout=15000)

            logged_in = "login" not in self.page.url
            logger.info(f"Wellfound: login {'success' if logged_in else 'failed'}")
            return logged_in
        except Exception as e:
            logger.warning(f"Wellfound: login error: {e}")
            return False

    async def search(self, query: str, location: str = "Remote") -> list[Job]:
        try:
            await self.page.goto(WELLFOUND_SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(3, 6)

            # Wait for React hydration — try multiple selectors
            found = False
            for selector in [
                '[class*="JobListing"]',
                '[data-test="JobListing"]',
                'div[class*="job"]',
                'div[class*="listing"]',
                'a[href*="/jobs/"]',
            ]:
                try:
                    await self.page.wait_for_selector(selector, timeout=8000)
                    found = True
                    break
                except Exception:
                    continue

            if not found:
                # Page may require login — skip gracefully
                logger.warning("Wellfound: job listings not visible (may require login)")
                return []

            await self.scroll_naturally()
        except Exception as e:
            logger.error(f"Wellfound: navigation error: {e}")
            return []

        jobs = []
        try:
            # Try multiple selector patterns for Wellfound's React SPA
            for selector in ['[class*="JobListing"]', 'article[class*="job"]', 'div[class*="listing"]']:
                cards = await self.page.locator(selector).all()
                if cards:
                    break

            for card in cards[:20]:
                try:
                    title_el = card.locator('h2 a, h3 a, [class*="title"] a').first
                    title = await self.safe_inner_text(title_el)
                    href = await self.safe_get_attribute(title_el, "href")

                    company_el = card.locator('[class*="company"], [class*="startup"]').first
                    company = await self.safe_inner_text(company_el)

                    location_el = card.locator('[class*="location"]').first
                    location_text = await self.safe_inner_text(location_el, default="Remote")

                    if not title or not href:
                        continue

                    full_url = f"https://wellfound.com{href}" if href.startswith("/") else href

                    jobs.append(Job(
                        title=title,
                        company=company or "Unknown",
                        location=location_text,
                        url=full_url,
                        source=JobSource.WELLFOUND,
                        is_remote=True,
                        easy_apply=True,
                    ))
                    await self.human_delay(0.3, 0.8)
                except Exception as e:
                    logger.debug(f"Wellfound: skipped card: {e}")

        except Exception as e:
            logger.error(f"Wellfound: card parsing error: {e}")

        logger.info(f"Wellfound: found {len(jobs)} jobs")
        return jobs

    async def apply(self, job: Job, cover_letter: str, resume_path: str) -> bool:
        try:
            await self.page.goto(job.url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(2, 4)

            # Click "Apply" or "Express Interest"
            apply_btn = self.page.locator('button:has-text("Apply"), button:has-text("Express Interest"), a:has-text("Apply")').first
            if await apply_btn.count() == 0 or not await apply_btn.is_visible():
                logger.info(f"Wellfound: no apply button found for {job.title}")
                return False

            await apply_btn.click()
            await self.human_delay(2, 4)

            # Wellfound may open a modal or redirect to company ATS
            # Handle modal form
            intro_field = self.page.locator('textarea[placeholder*="introduce"], textarea[name*="intro"]').first
            if await intro_field.count() > 0 and cover_letter:
                await intro_field.fill(cover_letter[:500])  # Wellfound intro is short
                await self.human_delay(0.5, 1)

            # Resume upload
            file_input = self.page.locator('input[type="file"]').first
            if await file_input.count() > 0 and resume_path:
                await file_input.set_input_files(resume_path)
                await self.human_delay(1, 2)

            # Submit the interest form
            submit_btn = self.page.locator('button:has-text("Send"), button:has-text("Submit"), button[type="submit"]').first
            if await submit_btn.count() > 0 and await submit_btn.is_visible():
                await submit_btn.click()
                await self.human_delay(2, 4)
                logger.info(f"Wellfound: applied to {job.title} at {job.company}")
                return True

        except Exception as e:
            logger.error(f"Wellfound: apply error for {job.title}: {e}")

        return False
