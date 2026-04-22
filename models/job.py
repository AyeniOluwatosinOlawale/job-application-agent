from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime
from typing import Optional


class JobSource(str, Enum):
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    REMOTIVE = "remotive"
    ARBEITNOW = "arbeitnow"
    WELLFOUND = "wellfound"
    REED = "reed"
    ADZUNA = "adzuna"
    CV_LIBRARY = "cv_library"
    TOTALJOBS = "totaljobs"


class ApplicationStatus(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"
    ALREADY_APPLIED = "already_applied"


class SeniorityLevel(str, Enum):
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    PRINCIPAL = "principal"
    UNKNOWN = "unknown"


class Job(BaseModel):
    id: Optional[str] = None
    title: str
    company: str
    location: str
    url: str
    source: JobSource
    description: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    is_remote: bool = False
    seniority: SeniorityLevel = SeniorityLevel.UNKNOWN
    posted_date: Optional[datetime] = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    easy_apply: bool = False
    external_apply_url: Optional[str] = None


class Application(BaseModel):
    job_id: str
    status: ApplicationStatus = ApplicationStatus.PENDING
    applied_at: Optional[datetime] = None
    cover_letter: Optional[str] = None
    notes: Optional[str] = None
    error_message: Optional[str] = None
    email_sent: bool = False


class AgentDecision(BaseModel):
    should_apply: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    seniority_detected: SeniorityLevel
    is_relevant: bool
    tailored_cover_letter: Optional[str] = None
    red_flags: list[str] = []
