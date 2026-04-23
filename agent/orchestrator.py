import json
from datetime import datetime
from openai import OpenAI
from config.settings import settings
from storage.database import Database
from models.job import Job, Application, ApplicationStatus
from loguru import logger
from applier.browser_use_applier import BrowserUseApplier, ApplicantProfile

SYSTEM_PROMPT = """You are an autonomous job application agent working on behalf of {applicant_name}.

Applicant details:
- Name: {applicant_name}
- Phone: {applicant_phone}
- Email: {applicant_email}
- LinkedIn: {linkedin_profile_url}
- CV: {cv_url}

Your goal: find and apply to relevant AI Engineer positions across multiple job platforms, focusing on UK-based and remote roles.

Decision criteria:
- Apply to roles matching: AI Engineer, ML Engineer, Applied AI Engineer, LLM Engineer, GenAI Engineer, Machine Learning Engineer
- Prefer remote or hybrid roles; UK-based roles are also acceptable
- Skip roles requiring >8 years experience (unless the role description is compelling)
- Skip duplicate companies applied to in the current session
- Generate authentic, specific cover letters — NEVER use placeholder text like [Your Name] or [Your Address]. Always use the real applicant details above.

Workflow — call tools in this order:
1. Call search_jobs for each platform: remotive, arbeitnow, reed, adzuna, cv_library, totaljobs
2. For each new job returned, call evaluate_job
3. For approved jobs, call generate_cover_letter
4. Call apply_to_job with the cover letter

When all platforms are searched and all approved applications submitted, end your turn.
"""

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": "Search for AI Engineer jobs on a specific platform. Returns a list of new job listings not previously seen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "enum": ["remotive", "arbeitnow", "reed", "adzuna", "cv_library", "totaljobs"],
                        "description": "The job platform to search",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query, e.g. 'AI Engineer'",
                    },
                    "location": {
                        "type": "string",
                        "description": "Location filter, e.g. 'Remote' or 'San Francisco'",
                    },
                },
                "required": ["platform", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_job",
            "description": "Evaluate whether a job is a good match and worth applying to. Returns a decision with reasoning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                },
                "required": ["job_id", "title", "company", "location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_cover_letter",
            "description": "Generate a tailored cover letter for a specific job.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["job_id", "title", "company"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_to_job",
            "description": "Submit an application to a specific job using the appropriate platform searcher.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "cover_letter": {
                        "type": "string",
                        "description": "The cover letter text to submit with the application",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
]


class AgentOrchestrator:
    def __init__(self, db: Database, searchers: dict, resume_path: str):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.db = db
        self.searchers = searchers
        self.resume_path = resume_path
        self._applied_companies: set[str] = set()

        profile = ApplicantProfile(
            name=settings.applicant_name,
            email=settings.gmail_address,
            phone=settings.applicant_phone,
            linkedin_url=settings.linkedin_profile_url,
            github_url=settings.github_url,
            cv_url=settings.cv_url,
            experience_years=settings.experience_years,
            target_role=settings.target_role,
            resume_path=resume_path,
        )
        try:
            first_searcher = next(iter(searchers.values()))
            self.browser_use_applier = BrowserUseApplier(
                profile=profile,
                browser=first_searcher.browser,
            )
            logger.info("BrowserUseApplier initialized")
        except Exception as e:
            logger.warning(f"BrowserUseApplier init failed — manual fallback active: {e}")
            self.browser_use_applier = None

    async def run(self) -> dict:
        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(
                    applicant_name=settings.applicant_name,
                    applicant_phone=settings.applicant_phone,
                    applicant_email=settings.gmail_address,
                    linkedin_profile_url=settings.linkedin_profile_url,
                    cv_url=settings.cv_url,
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Begin the job search and application cycle for '{settings.target_role}' roles. "
                    f"Target locations: {', '.join(settings.target_locations)}. "
                    f"Search all platforms (remotive, arbeitnow, reed, adzuna, cv_library, totaljobs), "
                    f"evaluate every result, and apply to matching positions."
                ),
            },
        ]

        stats = {"searched": 0, "evaluated": 0, "applied": 0, "failed": 0, "skipped": 0}

        while True:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                tools=AGENT_TOOLS,
                tool_choice="auto",
                max_tokens=2048,
            )

            message = response.choices[0].message
            messages.append(message)

            if not message.tool_calls:
                logger.info("Agent: completed cycle")
                break

            tool_results = []
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                logger.info(f"Agent: calling tool '{name}' with args {args}")

                result = await self._dispatch(name, args, stats)

                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })

            messages.extend(tool_results)

        logger.info(f"Agent stats: {stats}")
        return stats

    async def _dispatch(self, name: str, args: dict, stats: dict) -> dict:
        try:
            if name == "search_jobs":
                return await self._search_jobs(**args, stats=stats)
            elif name == "evaluate_job":
                return await self._evaluate_job(**args, stats=stats)
            elif name == "generate_cover_letter":
                return await self._generate_cover_letter(**args)
            elif name == "apply_to_job":
                return await self._apply_to_job(**args, stats=stats)
            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.error(f"Tool '{name}' error: {e}")
            return {"error": str(e)}

    async def _search_jobs(self, platform: str, query: str, location: str = "Remote", stats: dict = None) -> dict:
        searcher = self.searchers.get(platform)
        if not searcher:
            return {"error": f"No searcher for platform: {platform}"}

        jobs = await searcher.search(query=query, location=location)
        new_jobs = []

        for job in jobs:
            job.id = Database.generate_job_id(job.company, job.title, job.url)
            if not await self.db.job_exists(job.id):
                # Also skip if same company+title was already attempted (URL may vary across runs)
                if await self.db.title_company_applied(job.title, job.company):
                    continue
                await self.db.save_job(job)
                new_jobs.append({
                    "job_id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "source": job.source.value,
                    "description": (job.description or "")[:200],
                    "easy_apply": job.easy_apply,
                    "is_remote": job.is_remote,
                })

        # If no new jobs from live search, surface unapplied jobs already in DB for this platform
        if not new_jobs:
            unapplied = await self.db.get_unapplied_jobs(source=platform, limit=5)
            new_jobs = unapplied

        if stats is not None:
            stats["searched"] += len(new_jobs)

        return {"platform": platform, "new_jobs_found": len(new_jobs), "jobs": new_jobs}

    async def _evaluate_job(self, job_id: str, title: str, company: str, location: str,
                             description: str = "", stats: dict = None) -> dict:
        # Skip if already applied to this company this session
        if company.lower() in self._applied_companies:
            if stats:
                stats["skipped"] += 1
            return {"should_apply": False, "reason": f"Already applied to {company} this session"}

        # Quick LLM evaluation
        eval_response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict job relevance filter. Reply with JSON only: "
                        '{"should_apply": bool, "confidence": float 0-1, "seniority": str, "reasoning": str, "red_flags": [str]}\n\n'
                        "Rules:\n"
                        "- should_apply=true ONLY if the job title clearly matches: AI Engineer, ML Engineer, Machine Learning Engineer, "
                        "Applied AI, LLM Engineer, GenAI Engineer, NLP Engineer, Data Scientist (AI-focused), AI Research Engineer.\n"
                        "- should_apply=false for: Customer Success, Product Owner, ERP, Sales, Marketing, Finance, HR, "
                        "any role not directly engineering AI/ML systems.\n"
                        "- should_apply=false if the role requires >8 years experience."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Candidate: {settings.applicant_name}, targeting {settings.target_role}, "
                        f"{settings.experience_years} years AI/ML engineering experience.\n\n"
                        f"Job title: {title}\nCompany: {company}\nLocation: {location}\n"
                        f"Description snippet: {(description or '')[:500]}\n\n"
                        "Is this a relevant AI/ML engineering role? Should the candidate apply?"
                    ),
                },
            ],
            max_tokens=300,
            response_format={"type": "json_object"},
        )

        try:
            decision = json.loads(eval_response.choices[0].message.content)
        except Exception:
            decision = {"should_apply": True, "confidence": 0.5, "reasoning": "Parse error — defaulting to apply"}

        if stats:
            stats["evaluated"] += 1

        return decision

    async def _generate_cover_letter(self, job_id: str, title: str, company: str, description: str = "") -> dict:
        cl_response = self.client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write concise, compelling cover letters. "
                        "3-4 paragraphs max. Professional but warm tone. "
                        "Always reference something specific about the company or role. "
                        "Do not use generic filler phrases."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Write a cover letter for this applicant applying to the job below.\n\n"
                        f"APPLICANT:\n"
                        f"Name: {settings.applicant_name}\n"
                        f"Email: {settings.gmail_address}\n"
                        f"Phone: {settings.applicant_phone}\n"
                        f"LinkedIn: {settings.linkedin_profile_url}\n"
                        f"Experience: AI/ML Engineer with {settings.experience_years} years experience, "
                        f"skilled in LLMs, Python, ML pipelines, and production AI systems.\n\n"
                        f"JOB:\n"
                        f"Role: {title}\nCompany: {company}\n"
                        f"Description: {(description or '')[:1500]}\n\n"
                        f"Write a complete, ready-to-send cover letter. Do NOT use any placeholder text. "
                        f"Use the applicant's real name and details provided above."
                    ),
                },
            ],
            max_tokens=600,
        )

        cover_letter = cl_response.choices[0].message.content.strip()
        return {"job_id": job_id, "cover_letter": cover_letter}

    async def _apply_to_job(self, job_id: str, cover_letter: str = "", stats: dict = None) -> dict:
        job = await self.db.get_job(job_id)
        if not job:
            return {"error": f"Job {job_id} not found in database"}

        if await self.db.application_exists(job_id):
            return {"status": "already_applied", "job_id": job_id}

        app = Application(job_id=job_id)
        app.cover_letter = cover_letter

        from models.job import JobSource

        # Non-Reed sources: try AI-powered form fill, fall back to manual queue
        easy_apply_sources = {JobSource.REED}
        if job.source not in easy_apply_sources and not job.easy_apply:
            if self.browser_use_applier is not None:
                target_url = job.external_apply_url or job.url
                success, notes = await self.browser_use_applier.apply(
                    job_url=target_url,
                    job_title=job.title,
                    company=job.company,
                    cover_letter=cover_letter,
                )
                if success:
                    app.status = ApplicationStatus.APPLIED
                    app.applied_at = datetime.utcnow()
                    app.notes = notes
                    self._applied_companies.add(job.company.lower())
                    await self.db.save_application(app)
                    if stats:
                        stats["applied"] += 1
                    logger.info(f"AI-applied: {job.title} at {job.company}")
                    return {"status": "applied", "job_id": job_id, "title": job.title, "company": job.company}
                else:
                    logger.warning(f"browser-use failed ({notes}) — manual queue: {job.title}")
                    app.status = ApplicationStatus.SKIPPED
                    app.notes = f"manual_apply ({notes})"
                    await self.db.save_application(app)
                    if stats:
                        stats["skipped"] += 1
                    return {"status": "manual_apply", "job_id": job_id, "title": job.title, "company": job.company, "url": job.url}
            else:
                app.status = ApplicationStatus.SKIPPED
                app.notes = "manual_apply"
                await self.db.save_application(app)
                if stats:
                    stats["skipped"] += 1
                logger.info(f"Queued for manual apply: {job.title} at {job.company} ({job.url})")
                return {"status": "manual_apply", "job_id": job_id, "title": job.title, "company": job.company, "url": job.url}

        searcher = self.searchers.get(job.source.value)
        if not searcher:
            app.status = ApplicationStatus.FAILED
            app.error_message = f"No searcher for source: {job.source.value}"
            await self.db.save_application(app)
            return {"status": "failed", "reason": app.error_message}

        try:
            success = await searcher.apply(job, cover_letter, self.resume_path)

            if success:
                app.status = ApplicationStatus.APPLIED
                app.applied_at = datetime.utcnow()
                self._applied_companies.add(job.company.lower())
                if stats:
                    stats["applied"] += 1
                logger.info(f"Applied: {job.title} at {job.company}")
            else:
                app.status = ApplicationStatus.SKIPPED
                app.notes = "no apply button found"
                if stats:
                    stats["skipped"] += 1

        except Exception as e:
            app.status = ApplicationStatus.FAILED
            app.error_message = str(e)
            if stats:
                stats["failed"] += 1
            logger.error(f"apply_to_job error for {job.title}: {e}")
        finally:
            await self.db.save_application(app)

        return {
            "status": app.status.value,
            "job_id": job_id,
            "title": job.title,
            "company": job.company,
        }
