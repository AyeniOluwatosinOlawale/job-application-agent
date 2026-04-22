import aiosqlite
import hashlib
import json
from datetime import datetime, date
from models.job import Job, Application, ApplicationStatus, JobSource, SeniorityLevel
from loguru import logger

DB_PATH = "jobs.db"

CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    description TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    is_remote BOOLEAN DEFAULT 0,
    seniority TEXT DEFAULT 'unknown',
    posted_date TEXT,
    discovered_at TEXT NOT NULL,
    easy_apply BOOLEAN DEFAULT 0,
    external_apply_url TEXT
);
"""

CREATE_APPLICATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    status TEXT NOT NULL DEFAULT 'pending',
    applied_at TEXT,
    cover_letter TEXT,
    notes TEXT,
    error_message TEXT,
    email_sent BOOLEAN DEFAULT 0,
    UNIQUE(job_id)
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);",
    "CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);",
    "CREATE INDEX IF NOT EXISTS idx_applications_applied_at ON applications(applied_at);",
]


class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(CREATE_JOBS_TABLE)
            await db.execute(CREATE_APPLICATIONS_TABLE)
            for idx in CREATE_INDEXES:
                await db.execute(idx)
            await db.commit()
        logger.info(f"Database initialized at {self.db_path}")

    async def job_exists(self, job_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)) as cur:
                return await cur.fetchone() is not None

    async def url_exists(self, url: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT 1 FROM jobs WHERE url = ?", (url,)) as cur:
                return await cur.fetchone() is not None

    async def save_job(self, job: Job) -> bool:
        if await self.job_exists(job.id):
            return False
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    """INSERT OR IGNORE INTO jobs
                       (id, title, company, location, url, source, description,
                        salary_min, salary_max, is_remote, seniority,
                        posted_date, discovered_at, easy_apply, external_apply_url)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        job.id,
                        job.title,
                        job.company,
                        job.location,
                        job.url,
                        job.source.value,
                        job.description,
                        job.salary_min,
                        job.salary_max,
                        job.is_remote,
                        job.seniority.value,
                        job.posted_date.isoformat() if job.posted_date else None,
                        job.discovered_at.isoformat(),
                        job.easy_apply,
                        job.external_apply_url,
                    ),
                )
                await db.commit()
                return True
            except Exception as e:
                logger.error(f"save_job failed for {job.url}: {e}")
                return False

    async def save_application(self, app: Application) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO applications
                   (job_id, status, applied_at, cover_letter, notes, error_message, email_sent)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET
                     status=excluded.status,
                     applied_at=excluded.applied_at,
                     cover_letter=excluded.cover_letter,
                     notes=excluded.notes,
                     error_message=excluded.error_message,
                     email_sent=excluded.email_sent""",
                (
                    app.job_id,
                    app.status.value,
                    app.applied_at.isoformat() if app.applied_at else None,
                    app.cover_letter,
                    app.notes,
                    app.error_message,
                    app.email_sent,
                ),
            )
            await db.commit()

    async def get_job(self, job_id: str) -> Job | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cur:
                row = await cur.fetchone()
                if row is None:
                    return None
                return self._row_to_job(dict(row))

    async def title_company_applied(self, title: str, company: str) -> bool:
        """Return True if any job with this title+company has been applied/skipped/failed."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT 1 FROM jobs j
                   JOIN applications a ON a.job_id = j.id
                   WHERE LOWER(j.title) = LOWER(?) AND LOWER(j.company) = LOWER(?)
                     AND a.status IN ('applied', 'failed', 'skipped')
                   LIMIT 1""",
                (title.strip(), company.strip()),
            ) as cur:
                return await cur.fetchone() is not None

    async def get_unapplied_jobs(self, source: str | None = None, limit: int = 30) -> list[dict]:
        """Return jobs with no applied/failed/skipped application record."""
        query = """
            SELECT j.id as job_id, j.title, j.company, j.location,
                   j.url, j.source, j.description, j.easy_apply, j.is_remote
            FROM jobs j
            LEFT JOIN applications a ON a.job_id = j.id
                AND a.status IN ('applied', 'failed', 'skipped')
            WHERE a.job_id IS NULL
        """
        params = []
        if source:
            query += " AND j.source = ?"
            params.append(source)
        query += " ORDER BY j.discovered_at DESC LIMIT ?"
        params.append(limit)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def get_daily_summary(self) -> list[dict]:
        today = date.today().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT j.id as job_id, j.title, j.company, j.location,
                          j.url, j.source, a.status, a.applied_at, a.email_sent,
                          a.cover_letter, a.notes
                   FROM applications a
                   JOIN jobs j ON j.id = a.job_id
                   WHERE DATE(a.applied_at) = ?
                     AND a.email_sent = 0
                     AND a.status IN ('applied', 'failed')""",
                (today,),
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def get_manual_apply_jobs(self) -> list[dict]:
        """Return today's jobs queued for manual application (with cover letters)."""
        today = date.today().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT j.id as job_id, j.title, j.company, j.location,
                          j.url, j.source, a.cover_letter, a.email_sent
                   FROM applications a
                   JOIN jobs j ON j.id = a.job_id
                   WHERE a.status = 'skipped'
                     AND a.notes = 'manual_apply'
                     AND a.email_sent = 0
                     AND DATE(a.applied_at) IS NULL
                   ORDER BY j.discovered_at DESC
                   LIMIT 20""",
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def mark_email_sent(self, job_ids: list[str]) -> None:
        if not job_ids:
            return
        async with aiosqlite.connect(self.db_path) as db:
            placeholders = ",".join("?" * len(job_ids))
            await db.execute(
                f"UPDATE applications SET email_sent = 1 WHERE job_id IN ({placeholders})",
                job_ids,
            )
            await db.commit()

    async def application_exists(self, job_id: str) -> bool:
        """Return True if already applied OR failed — prevents infinite retries."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM applications WHERE job_id = ? AND status IN ('applied', 'failed', 'skipped')",
                (job_id,),
            ) as cur:
                return await cur.fetchone() is not None

    @staticmethod
    def generate_job_id(company: str, title: str, url: str) -> str:
        payload = f"{company.lower().strip()}:{title.lower().strip()}:{url.strip()}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @staticmethod
    def _row_to_job(row: dict) -> Job:
        return Job(
            id=row["id"],
            title=row["title"],
            company=row["company"],
            location=row["location"],
            url=row["url"],
            source=JobSource(row["source"]),
            description=row.get("description"),
            salary_min=row.get("salary_min"),
            salary_max=row.get("salary_max"),
            is_remote=bool(row.get("is_remote", False)),
            seniority=SeniorityLevel(row.get("seniority", "unknown")),
            easy_apply=bool(row.get("easy_apply", False)),
            external_apply_url=row.get("external_apply_url"),
        )
