import asyncio
import random
from dataclasses import dataclass
from loguru import logger

LINKEDIN_PROFILE_DIR = ".linkedin_browser_profile"
LINKEDIN_DAILY_APPLY_CAP = 10
_linkedin_applied_today = 0


@dataclass
class ApplicantProfile:
    name: str
    email: str
    phone: str
    linkedin_url: str
    github_url: str
    cv_url: str
    experience_years: int
    target_role: str
    resume_path: str
    linkedin_email: str = ""
    linkedin_password: str = ""


class BrowserUseApplier:
    """AI-powered form filler using browser-use (0.12.x API)."""

    TIMEOUT_SECONDS = 120
    MAX_STEPS = 20
    LINKEDIN_MAX_STEPS = 25

    def __init__(self, profile: ApplicantProfile, browser=None):
        self.profile = profile
        self.browser = browser

    async def apply(
        self,
        job_url: str,
        job_title: str,
        company: str,
        cover_letter: str,
    ) -> tuple[bool, str]:
        """Apply to a non-LinkedIn job using AI-driven form filling."""
        try:
            from browser_use import Agent
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            logger.error(f"browser-use not installed: {e}")
            return False, "browser_use_not_installed"

        task = self._build_task(job_url, job_title, company, cover_letter)

        try:
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            agent = Agent(task=task, llm=llm, max_steps=self.MAX_STEPS)
            result = await asyncio.wait_for(agent.run(), timeout=self.TIMEOUT_SECONDS)
            success = self._parse_result(result)
            notes = "browser_use_applied" if success else "browser_use_incomplete"
            logger.info(f"BrowserUseApplier: {'success' if success else 'incomplete'} — {job_title} at {company}")
            return success, notes

        except asyncio.TimeoutError:
            logger.warning(f"BrowserUseApplier: timeout ({self.TIMEOUT_SECONDS}s) — {job_title} at {company}")
            return False, "browser_use_timeout"
        except Exception as e:
            logger.error(f"BrowserUseApplier: error for {job_title} at {company}: {e}")
            return False, f"browser_use_error:{type(e).__name__}"

    async def apply_linkedin(
        self,
        job_url: str,
        job_title: str,
        company: str,
        cover_letter: str,
    ) -> tuple[bool, str]:
        """Apply to a LinkedIn job via Easy Apply using stealth browser-use."""
        global _linkedin_applied_today

        if _linkedin_applied_today >= LINKEDIN_DAILY_APPLY_CAP:
            logger.warning(f"LinkedIn daily cap ({LINKEDIN_DAILY_APPLY_CAP}) reached — skipping")
            return False, "linkedin_daily_cap"

        try:
            from browser_use import Agent
            from browser_use.browser.browser import Browser, BrowserConfig
            from langchain_openai import ChatOpenAI
        except ImportError as e:
            logger.error(f"browser-use not installed: {e}")
            return False, "browser_use_not_installed"

        task = self._build_linkedin_task(job_url, job_title, company, cover_letter)

        try:
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

            # Stealth browser config — mimics a real user session
            config = BrowserConfig(
                headless=True,
                user_data_dir=LINKEDIN_PROFILE_DIR,
                extra_chromium_args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--window-size=1280,800",
                    "--disable-extensions",
                ],
            )
            browser = Browser(config=config)
            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
                max_steps=self.LINKEDIN_MAX_STEPS,
            )

            # Human-like random pre-delay before each LinkedIn action
            await asyncio.sleep(random.uniform(3, 8))

            result = await asyncio.wait_for(agent.run(), timeout=180)
            await browser.close()

            success = self._parse_result(result)
            if success:
                _linkedin_applied_today += 1
                logger.info(f"LinkedIn AI-applied ({_linkedin_applied_today}/{LINKEDIN_DAILY_APPLY_CAP}): {job_title} at {company}")
                return True, "linkedin_browser_use_applied"
            else:
                logger.warning(f"LinkedIn browser-use incomplete: {job_title} at {company}")
                return False, "linkedin_browser_use_incomplete"

        except asyncio.TimeoutError:
            logger.warning(f"LinkedIn browser-use timeout: {job_title} at {company}")
            return False, "linkedin_timeout"
        except Exception as e:
            logger.error(f"LinkedIn browser-use error for {job_title}: {e}")
            return False, f"linkedin_error:{type(e).__name__}"

    def _build_task(self, job_url: str, job_title: str, company: str, cover_letter: str) -> str:
        p = self.profile
        return f"""You are completing a job application on behalf of {p.name}.

TASK: Navigate to {job_url} and submit a complete application for "{job_title}" at "{company}".

APPLICANT DETAILS — use these exact values, never placeholders:
- Full Name: {p.name}
- Email: {p.email}
- Phone: {p.phone}
- LinkedIn: {p.linkedin_url}
- GitHub: {p.github_url}
- Years of Experience: {p.experience_years}
- Target Role: {p.target_role}

RESUME FILE PATH: {p.resume_path}

COVER LETTER (paste into any cover letter / additional information field):
{cover_letter}

INSTRUCTIONS:
1. Dismiss any cookie consent banners first.
2. Find and click the Apply / Apply Now / Easy Apply button.
3. If it opens a new tab, continue in that tab.
4. Fill every required field using the applicant details above.
5. Upload the resume PDF when a file upload field appears.
6. For right-to-work in UK questions: answer Yes.
7. For visa sponsorship required questions: answer No.
8. For years of experience numeric fields: enter {p.experience_years}.
9. For salary fields: leave blank or enter 0 if required.
10. Click Next / Continue through all steps until the final Submit button.
11. Click Submit and confirm the "Application submitted" or "Thank you" message.
12. Stop immediately if you encounter a CAPTCHA — report failure.
13. Stop immediately if a login wall appears that cannot be bypassed.
"""

    def _build_linkedin_task(self, job_url: str, job_title: str, company: str, cover_letter: str) -> str:
        p = self.profile
        login_instruction = ""
        if p.linkedin_email and p.linkedin_password:
            login_instruction = f"""
If you are NOT already logged in to LinkedIn:
- Go to https://www.linkedin.com/login
- Enter email: {p.linkedin_email}
- Enter password: {p.linkedin_password}
- Click Sign in and wait for the feed page to load
- If a CAPTCHA or verification appears, stop and report failure immediately
"""
        return f"""You are completing a LinkedIn job application on behalf of {p.name}.

TASK: Apply to "{job_title}" at "{company}" via LinkedIn Easy Apply.
Job URL: {job_url}

APPLICANT DETAILS — use these exact values:
- Full Name: {p.name}
- Email: {p.email}
- Phone: {p.phone}
- LinkedIn Profile: {p.linkedin_url}
- Years of Experience: {p.experience_years}
- Current/Target Role: {p.target_role}

RESUME FILE PATH: {p.resume_path}

COVER LETTER (paste into any cover letter field):
{cover_letter}

INSTRUCTIONS:
{login_instruction}
1. Navigate to {job_url}
2. Find the "Easy Apply" button and click it (do NOT click "Apply" which goes to external site)
3. If no Easy Apply button exists, stop and report "no_easy_apply"
4. Work through each step of the modal form:
   - Fill phone number if asked: {p.phone}
   - For resume: upload file from {p.resume_path}
   - For cover letter / additional information: paste the cover letter above
   - For Yes/No questions about right-to-work in UK: select Yes
   - For visa sponsorship questions: select No
   - For years of experience: enter {p.experience_years}
   - For salary questions: leave blank or enter 0
   - For "How did you hear about us": select LinkedIn or Other
5. Click Next / Continue / Review to advance through all steps
6. On the final Review screen, click Submit application
7. Confirm the "Your application was sent" confirmation message
8. Stop immediately if you see a CAPTCHA or phone verification — report failure
9. Move naturally between fields with small pauses — do not rush
"""

    @staticmethod
    def _parse_result(result) -> bool:
        try:
            if hasattr(result, "is_successful") and result.is_successful():
                return True
            if hasattr(result, "final_result"):
                final = str(result.final_result() or "").lower()
                return any(w in final for w in ["submitted", "thank you", "success", "applied", "received", "sent"])
            if hasattr(result, "history") and result.history:
                last_str = str(result.history[-1]).lower()
                return any(w in last_str for w in ["submitted", "thank you", "success", "applied", "received", "sent"])
        except Exception:
            pass
        return False
