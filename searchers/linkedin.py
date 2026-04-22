import json
import os
from searchers.base import BaseSearcher
from models.job import Job, JobSource
from config.settings import settings
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from loguru import logger

# Public job search — no login required
LINKEDIN_PUBLIC_SEARCH_URL = (
    "https://www.linkedin.com/jobs/search"
    "?keywords={query}"
    "&location={location}"
    "&f_TPR=r86400"   # past 24 hours
    "&sortBy=DD"
    "&position=1&pageNum=0"
)

LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"
PROFILE_DIR = os.path.abspath(".linkedin_profile")
MAX_JOBS_PER_RUN = 15


class LinkedInSearcher(BaseSearcher):

    def __init__(self, browser):
        super().__init__(browser)
        self._logged_in = False

    async def login(self) -> bool:
        """Use persistent profile if available, otherwise public mode."""
        if os.path.isdir(PROFILE_DIR):
            if await self._try_profile_login():
                self._logged_in = True
                return True
        logger.info("LinkedIn: using public search mode (no login) — run linkedin_setup.py to enable applying")
        return True

    async def _try_profile_login(self) -> bool:
        """Navigate to feed using the saved persistent profile context."""
        try:
            await self.page.goto(LINKEDIN_FEED_URL, wait_until="domcontentloaded", timeout=20000)
            await self.human_delay(2, 3)
            # Must be on the actual feed path — not a login redirect that contains "feed" in params
            from urllib.parse import urlparse
            parsed = urlparse(self.page.url)
            if parsed.netloc == "www.linkedin.com" and parsed.path.startswith("/feed"):
                logger.info("LinkedIn: logged in via persistent profile")
                return True
            logger.info(f"LinkedIn: profile session expired (at {self.page.url[:60]}) — using public mode")
        except Exception as e:
            logger.debug(f"LinkedIn: profile login failed: {e}")
        return False

    async def search(self, query: str, location: str = "Remote") -> list[Job]:
        url = LINKEDIN_PUBLIC_SEARCH_URL.format(
            query=query.replace(" ", "%20"),
            location=location.replace(" ", "%20"),
        )
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(3, 5)
        except Exception as e:
            logger.error(f"LinkedIn: navigation error: {e}")
            return []

        # Dismiss any consent/cookie overlay
        await self._dismiss_consent()

        jobs = []
        try:
            # Try logged-in selectors first, fall back to public selectors
            logged_in_selector = (
                ".job-card-container, .scaffold-layout__list-item, "
                ".jobs-search-results__list-item"
            )
            public_selector = ".base-card, .job-search-card, [data-entity-urn]"

            is_logged_in_page = False
            try:
                await self.page.wait_for_selector(logged_in_selector, timeout=8000)
                is_logged_in_page = True
                logger.debug("LinkedIn: using logged-in search selectors")
            except Exception:
                try:
                    await self.page.wait_for_selector(public_selector, timeout=8000)
                    logger.debug("LinkedIn: using public search selectors")
                except Exception:
                    logger.error("LinkedIn: no job card selectors found on search page")
                    return []

            await self.scroll_naturally()

            if is_logged_in_page:
                cards = await self.page.locator(".job-card-container").all()
                cards = cards[:MAX_JOBS_PER_RUN]

                for card in cards:
                    try:
                        # Title + URL from the job link
                        link_el = card.locator("a[href*='/jobs/view/']").first
                        href = await self.safe_get_attribute(link_el, "href")
                        # Use aria-hidden strong to avoid duplicating visually-hidden text
                        strong_el = link_el.locator('[aria-hidden="true"] strong, strong').first
                        title = await self.safe_inner_text(strong_el)
                        if not title:
                            title = await self.safe_inner_text(link_el)
                            # Deduplicate: "X Y X Y" → "X Y"
                            words = title.split()
                            mid = len(words) // 2
                            if words[:mid] == words[mid:]:
                                title = " ".join(words[:mid])
                        title = " ".join(title.split())

                        company_el = card.locator(".artdeco-entity-lockup__subtitle").first
                        company = await self.safe_inner_text(company_el)

                        location_el = card.locator(".artdeco-entity-lockup__caption").first
                        location_text = await self.safe_inner_text(location_el)

                        if not title or not href:
                            continue

                        clean_url = href.split("?")[0]
                        if not clean_url.startswith("http"):
                            clean_url = f"https://www.linkedin.com{clean_url}"

                        jobs.append(Job(
                            title=title,
                            company=company or "Unknown",
                            location=location_text or location,
                            url=clean_url,
                            source=JobSource.LINKEDIN,
                            is_remote="remote" in location_text.lower(),
                            easy_apply=self._logged_in,
                            external_apply_url=clean_url,
                        ))
                        await self.human_delay(0.3, 0.8)
                    except Exception as e:
                        logger.debug(f"LinkedIn: skipped logged-in card: {e}")
            else:
                cards = await self.page.locator(".base-card, .job-search-card").all()
                cards = cards[:MAX_JOBS_PER_RUN]

                for card in cards:
                    try:
                        title_el = card.locator(
                            ".base-search-card__title, h3.base-search-card__title"
                        ).first
                        title = await self.safe_inner_text(title_el)

                        company_el = card.locator(
                            ".base-search-card__subtitle a, h4.base-search-card__subtitle"
                        ).first
                        company = await self.safe_inner_text(company_el)

                        location_el = card.locator(
                            ".job-search-card__location, .base-search-card__metadata"
                        ).first
                        location_text = await self.safe_inner_text(location_el)

                        link_el = card.locator("a.base-card__full-link, a[href*='/jobs/view/']").first
                        href = await self.safe_get_attribute(link_el, "href")

                        if not title or not href:
                            continue

                        clean_url = href.split("?")[0]
                        if not clean_url.startswith("http"):
                            clean_url = f"https://www.linkedin.com{clean_url}"

                        jobs.append(Job(
                            title=title,
                            company=company or "Unknown",
                            location=location_text or location,
                            url=clean_url,
                            source=JobSource.LINKEDIN,
                            is_remote="remote" in location_text.lower(),
                            easy_apply=self._logged_in,
                            external_apply_url=clean_url,
                        ))
                        await self.human_delay(0.4, 1.0)
                    except Exception as e:
                        logger.debug(f"LinkedIn: skipped public card: {e}")

        except Exception as e:
            logger.error(f"LinkedIn: card parsing error: {e}")

        mode = "logged-in" if self._logged_in else "public"
        logger.info(f"LinkedIn: found {len(jobs)} jobs ({mode} mode)")
        return jobs

    async def _dismiss_consent(self) -> None:
        """Dismiss LinkedIn's cookie/consent overlay if present."""
        for selector in [
            'button[action-type="ACCEPT"]',
            'button:has-text("Accept all")',
            'button:has-text("Accept cookies")',
            'button:has-text("Accept")',
        ]:
            try:
                btn = self.page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                    await btn.click()
                    await self.human_delay(1, 2)
                    return
            except Exception:
                pass

        # Remove consent overlay via JS as fallback
        try:
            await self.page.evaluate("""
                () => {
                    ['[class*="consent"]', '[class*="cookie-banner"]',
                     '[id*="consent"]', '.artdeco-global-alert-container']
                    .forEach(sel => {
                        document.querySelectorAll(sel).forEach(el => el.remove());
                    });
                }
            """)
        except Exception:
            pass

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=4, max=15),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def apply(self, job: Job, cover_letter: str, resume_path: str) -> bool:
        """
        Try Easy Apply if logged in, then fall back to external ATS form.
        In public mode (no login), skip — LinkedIn requires auth to apply.
        """
        if not self._logged_in:
            logger.info(f"LinkedIn (public mode): login required to apply — skipping {job.title}")
            return False

        try:
            await self.page.goto(job.url, wait_until="domcontentloaded", timeout=30000)
            await self.human_delay(3, 5)
            await self._dismiss_consent()

            current_url = self.page.url
            logger.debug(f"LinkedIn apply: at {current_url}")

            # Detect session expiry redirect
            if any(p in current_url for p in ["/login", "/uas/login", "/checkpoint"]):
                logger.warning("LinkedIn: redirected to login — session expired, cannot apply")
                return False

            # Scroll to top to ensure the apply button area is in view
            await self.page.evaluate("window.scrollTo(0, 0)")
            await self.human_delay(0.5, 1)

            # Wait for the job detail top-card to render (apply button lives here)
            try:
                await self.page.wait_for_selector(
                    ".jobs-unified-top-card, .job-view-layout, .jobs-details__main-content, "
                    ".jobs-s-apply, .jobs-apply-button, button.apply-button",
                    timeout=15000,
                )
            except Exception:
                logger.debug(f"LinkedIn: job detail container not found for {job.title}")

            await self.human_delay(1.5, 2.5)

            # Log visible buttons for debugging
            try:
                btns = await self.page.locator("button:visible").all()
                texts = []
                for b in btns[:15]:
                    t = await self.safe_inner_text(b)
                    if t:
                        texts.append(t[:40])
                logger.debug(f"LinkedIn: visible buttons: {texts}")
            except Exception:
                pass

            # ── Find main apply button (Easy Apply or external Apply) ────────
            apply_btn = None
            apply_btn_text = ""

            # Wait up to 10s for the apply button to appear (it often loads after DOM)
            for sel in [
                'button.jobs-apply-button',   # logged-in job detail pages
                'button.apply-button',        # alternate LinkedIn class seen in the wild
                'button[aria-label*="Easy Apply"]',
                'button[aria-label*="Apply"]',
                'button:has-text("Easy Apply")',
                '.jobs-s-apply button',
            ]:
                try:
                    candidate = self.page.locator(sel).first
                    await candidate.wait_for(state="visible", timeout=8000)
                    apply_btn = candidate
                    apply_btn_text = (await self.safe_inner_text(candidate)).lower()
                    logger.info(f"LinkedIn: apply button found ('{apply_btn_text}') with selector {sel}")
                    break
                except Exception:
                    pass

            if apply_btn is None:
                # Last-resort: any visible button containing "apply"
                for b in await self.page.locator("button:visible").all():
                    txt = (await self.safe_inner_text(b)).lower()
                    if "apply" in txt:
                        apply_btn = b
                        apply_btn_text = txt
                        logger.info(f"LinkedIn: fallback apply button found: '{txt}'")
                        break

            if apply_btn is None:
                # Check if it's an "I'm interested" type posting (no apply button)
                try:
                    interested = self.page.locator("button:has-text(\"I'm interested\")").first
                    if await interested.count() > 0:
                        logger.info(f"LinkedIn: '{job.title}' is 'I'm interested' type — no direct apply, skipping")
                    else:
                        logger.info(f"LinkedIn: no apply button found for '{job.title}' — job may not be accepting applications")
                except Exception:
                    logger.info(f"LinkedIn: no apply button found for '{job.title}'")
                return False

            # ── Easy Apply: opens a modal on the same page ────────────────────
            if "easy apply" in apply_btn_text:
                return await self._do_easy_apply(apply_btn, cover_letter, resume_path)

            # ── External Apply: opens a new tab ──────────────────────────────
            try:
                async with self.page.context.expect_page() as new_page_info:
                    await apply_btn.click()
                new_page = await new_page_info.value
                await new_page.wait_for_load_state("domcontentloaded", timeout=20000)
                await self.human_delay(2, 4)
                logger.info(f"LinkedIn: external apply page opened: {new_page.url[:80]}")
                result = await self._apply_on_page(new_page, cover_letter, resume_path)
                await new_page.close()
                return result
            except Exception:
                # LinkedIn might navigate in same tab instead of new tab
                await apply_btn.click()
                await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
                await self.human_delay(2, 4)
                if "linkedin.com" not in self.page.url:
                    return await self._apply_on_page(self.page, cover_letter, resume_path)

        except Exception as e:
            logger.error(f"LinkedIn: apply error for {job.title}: {e}")
        return False

    async def _do_easy_apply(self, apply_btn, cover_letter: str, resume_path: str) -> bool:
        await apply_btn.click()
        await self.human_delay(1.5, 3)

        for step in range(10):
            await self.human_delay(1, 2.5)
            logger.debug(f"LinkedIn Easy Apply: step {step + 1}")

            # Upload resume if file input present
            resume_input = self.page.locator('input[type="file"]').first
            if await resume_input.count() > 0 and resume_path:
                try:
                    await resume_input.set_input_files(resume_path)
                    await self.human_delay(1, 2)
                except Exception as e:
                    logger.debug(f"LinkedIn Easy Apply: resume upload error: {e}")

            # Fill cover letter if present
            for cl_sel in [
                'textarea[id*="cover"]',
                'textarea[name*="cover"]',
                'textarea[aria-label*="cover" i]',
                'textarea[aria-label*="letter" i]',
            ]:
                cl_field = self.page.locator(cl_sel).first
                if await cl_field.count() > 0 and await cl_field.is_visible() and cover_letter:
                    try:
                        if not await cl_field.input_value():
                            await cl_field.fill(cover_letter)
                    except Exception:
                        pass
                    break

            # Auto-answer Yes/No radio questions
            for radio in await self.page.locator('input[type="radio"][value="Yes"]').all():
                try:
                    if not await radio.is_checked():
                        await radio.click()
                        await self.human_delay(0.2, 0.5)
                except Exception:
                    pass

            # Fill required text inputs that are empty (phone, years of experience, etc.)
            for inp in await self.page.locator('input[type="text"]:visible, input[type="tel"]:visible').all():
                try:
                    val = await inp.input_value()
                    if not val:
                        label_text = (await inp.get_attribute("aria-label") or "").lower()
                        if "phone" in label_text:
                            await inp.fill("07727305230")
                        elif "year" in label_text or "experience" in label_text:
                            await inp.fill("3")
                        await self.human_delay(0.2, 0.5)
                except Exception:
                    pass

            # Check for submit button
            submit_btn = self.page.locator(
                'button[aria-label="Submit application"], '
                'button:has-text("Submit application"), '
                'button:has-text("Submit")'
            ).first
            if await submit_btn.count() > 0 and await submit_btn.is_visible():
                await submit_btn.click()
                await self.human_delay(2, 4)
                logger.info("LinkedIn: Easy Apply submitted successfully")
                return True

            # Advance to next step
            next_btn = self.page.locator(
                'button[aria-label="Continue to next step"], '
                'button:has-text("Next"), '
                'button:has-text("Review")'
            ).first
            if await next_btn.count() > 0 and await next_btn.is_visible():
                await next_btn.click()
                logger.debug(f"LinkedIn Easy Apply: advanced to next step")
            else:
                logger.debug(f"LinkedIn Easy Apply: no next/submit button found at step {step + 1}")
                break

        logger.warning("LinkedIn: Easy Apply exhausted steps without submitting")
        return False

    async def _apply_on_page(self, page, cover_letter: str, resume_path: str) -> bool:
        """Fill a generic ATS form (Greenhouse, Lever, Workday, etc.) on the given page."""
        from playwright.async_api import Page as PlaywrightPage

        # Resume upload
        try:
            file_input = page.locator('input[type="file"]').first
            if await file_input.count() > 0 and resume_path:
                await file_input.set_input_files(resume_path)
                await self.human_delay(1, 2)
        except Exception as e:
            logger.debug(f"LinkedIn external apply: resume upload failed: {e}")

        # Cover letter textarea
        try:
            for ta in await page.locator("textarea").all():
                placeholder = (await ta.get_attribute("placeholder") or "").lower()
                label = (await ta.get_attribute("aria-label") or "").lower()
                if any(k in placeholder or k in label for k in ["cover", "letter", "message"]):
                    await ta.fill(cover_letter)
                    await self.human_delay(0.5, 1)
                    break
        except Exception as e:
            logger.debug(f"LinkedIn external apply: cover letter failed: {e}")

        # Submit
        for selector in [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Submit")',
            'button:has-text("Apply")',
            'button:has-text("Submit application")',
        ]:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0 and await btn.is_visible(timeout=3000):
                    await btn.click()
                    await self.human_delay(2, 4)
                    logger.info("LinkedIn: external ATS form submitted")
                    return True
            except Exception:
                pass

        return False

    async def _apply_generic_form(self, cover_letter: str, resume_path: str) -> bool:
        return await self._apply_on_page(self.page, cover_letter, resume_path)
