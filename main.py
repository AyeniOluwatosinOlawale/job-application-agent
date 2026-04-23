import asyncio
import sys
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from playwright.async_api import async_playwright, Browser
from loguru import logger

from config.settings import settings
from agent.orchestrator import AgentOrchestrator
from storage.database import Database
from searchers.remotive import RemotiveSearcher
from searchers.arbeitnow import ArbeitnowSearcher
from searchers.reed import ReedSearcher
from searchers.adzuna import AdzunaSearcher
from searchers.cv_library import CvLibrarySearcher
from searchers.totaljobs import TotaljobsSearcher
from searchers.linkedin import LinkedInSearcher
from notifier.email_sender import EmailSender

# ── Logging setup ────────────────────────────────────────────────────────────
logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
)
logger.add(
    "logs/agent_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    level="DEBUG",
    encoding="utf-8",
)

RESUME_PATH = "resume_generated.pdf"

db = Database()
notifier = EmailSender()


async def export_cv_to_pdf(browser: Browser) -> bool:
    """Download the live CV as a PDF before any applications run."""
    logger.info(f"Exporting CV from {settings.cv_url}")
    try:
        page = await browser.new_page()
        await page.goto(settings.cv_url, wait_until="networkidle", timeout=30000)
        await page.pdf(path=RESUME_PATH, format="A4", print_background=True)
        await page.close()
        logger.info(f"CV exported to {RESUME_PATH}")
        return True
    except Exception as e:
        logger.error(f"CV export failed: {e}")
        return False


async def run_agent_cycle() -> None:
    logger.info("=" * 60)
    logger.info("Starting job application cycle")
    logger.info("=" * 60)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
            ],
        )

        # Export CV to PDF first
        cv_ok = await export_cv_to_pdf(browser)
        if not cv_ok:
            logger.warning("Proceeding without fresh CV export")

        searcher_classes = {
            "linkedin": LinkedInSearcher,
            "remotive": RemotiveSearcher,
            "arbeitnow": ArbeitnowSearcher,
            "reed": ReedSearcher,
            "adzuna": AdzunaSearcher,
            "cv_library": CvLibrarySearcher,
            "totaljobs": TotaljobsSearcher,
        }

        searchers = {}
        for name, cls in searcher_classes.items():
            s = cls(browser)
            await s.setup()
            logged_in = await s.login()
            if not logged_in:
                logger.warning(f"{name}: login failed — searches may be limited")
            searchers[name] = s

        try:
            orchestrator = AgentOrchestrator(db=db, searchers=searchers, resume_path=RESUME_PATH)
            stats = await orchestrator.run()
            logger.info(f"Cycle complete: {stats}")
        finally:
            for name, s in searchers.items():
                await s.teardown()
            await browser.close()

    # Send daily email summary
    summary = await db.get_daily_summary()
    manual_jobs = await db.get_manual_apply_jobs()

    if summary or manual_jobs:
        sent = notifier.send_daily_summary(summary, manual_jobs)
        if sent:
            all_ids = [row["job_id"] for row in summary] + [row["job_id"] for row in manual_jobs]
            await db.mark_email_sent(all_ids)
    else:
        logger.info("No new applications today — no email sent")

    logger.info("=" * 60)
    logger.info("Cycle finished")
    logger.info("=" * 60)


async def main() -> None:
    await db.initialize()

    if "--once" in sys.argv:
        logger.info("Running in one-shot mode (--once)")
        await run_agent_cycle()
        return

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_agent_cycle,
        trigger=IntervalTrigger(hours=settings.run_interval_hours),
        id="agent_cycle",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started — running every {settings.run_interval_hours}h")
    logger.info("Press Ctrl+C to stop")

    # Run immediately on startup, then on schedule
    await run_agent_cycle()

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
