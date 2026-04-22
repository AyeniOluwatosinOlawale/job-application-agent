from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
import json


class Settings(BaseSettings):
    # OpenAI
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4o", alias="OPENAI_MODEL")

    # Gmail SMTP
    gmail_address: str = Field(..., alias="GMAIL_ADDRESS")
    gmail_app_password: str = Field(..., alias="GMAIL_APP_PASSWORD")
    notification_email: str = Field(..., alias="NOTIFICATION_EMAIL")

    # LinkedIn (optional — not used in current run)
    linkedin_email: str = Field("", alias="LINKEDIN_EMAIL")
    linkedin_password: str = Field("", alias="LINKEDIN_PASSWORD")

    # Adzuna (optional — falls back to browser scrape if not set)
    adzuna_app_id: str = Field("", alias="ADZUNA_APP_ID")
    adzuna_app_key: str = Field("", alias="ADZUNA_APP_KEY")

    # Applicant profile
    applicant_name: str = Field(..., alias="APPLICANT_NAME")
    applicant_phone: str = Field("", alias="APPLICANT_PHONE")
    cv_url: str = Field("https://oluwatosin-ayeni-cv.netlify.app/", alias="CV_URL")
    linkedin_profile_url: str = Field("", alias="LINKEDIN_PROFILE_URL")
    github_url: str = Field("", alias="GITHUB_URL")

    # Search config
    target_role: str = Field("AI Engineer", alias="TARGET_ROLE")
    target_locations_raw: str = Field('["Remote"]', alias="TARGET_LOCATIONS")
    min_salary: Optional[int] = Field(None, alias="MIN_SALARY", validate_default=False)
    experience_years: int = Field(3, alias="EXPERIENCE_YEARS")

    # Schedule
    run_interval_hours: int = Field(24, alias="RUN_INTERVAL_HOURS")

    # Anti-detection
    min_delay_seconds: float = Field(2.0, alias="MIN_DELAY_SECONDS")
    max_delay_seconds: float = Field(7.0, alias="MAX_DELAY_SECONDS")

    @property
    def target_locations(self) -> list[str]:
        try:
            return json.loads(self.target_locations_raw)
        except Exception:
            return ["Remote"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "populate_by_name": True}


settings = Settings()
