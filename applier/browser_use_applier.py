import asyncio
from dataclasses import dataclass
from typing import Optional
from loguru import logger


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


class BrowserUseApplier:
    """AI-powered form filler using browser-use v0.1.48."""

    TIMEOUT_SECONDS = 120
    MAX_STEPS = 15

    def __init__(self, profile: ApplicantProfile, browser=None):
        self.profile = profile
        self.browser = browser
        self._agent_cls = None
        self._llm_cls = None

    def _load_deps(self):
        if self._agent_cls is None:
            from browser_use import Agent
            from langchain_openai import ChatOpenAI
            self._agent_cls = Agent
            self._llm_cls = ChatOpenAI

    async def apply(
        self,
        job_url: str,
        job_title: str,
        company: str,
        cover_letter: str,
    ) -> tuple[bool, str]:
        """
        Navigate to job_url and complete the application using LLM-driven browser.
        Returns (success, notes) — always falls back gracefully on failure.
        """
        try:
            self._load_deps()
        except ImportError as e:
            logger.error(f"browser-use not installed: {e}")
            return False, "browser_use_not_installed"

        task = self._build_task(job_url, job_title, company, cover_letter)

        try:
            llm = self._llm_cls(model="gpt-4o-mini", temperature=0)

            kwargs = dict(task=task, llm=llm, max_steps=self.MAX_STEPS)
            if self.browser is not None:
                kwargs["browser"] = self.browser

            agent = self._agent_cls(**kwargs)

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
12. Stop immediately if you encounter a CAPTCHA — report failure without attempting to solve it.
13. Stop immediately if a login/account-creation wall appears that cannot be bypassed.
"""

    @staticmethod
    def _parse_result(result) -> bool:
        try:
            if hasattr(result, "is_done") and result.is_done():
                return True
            if hasattr(result, "history") and result.history:
                last_str = str(result.history[-1]).lower()
                return any(w in last_str for w in ["submitted", "thank you", "success", "applied", "received"])
        except Exception:
            pass
        return False
