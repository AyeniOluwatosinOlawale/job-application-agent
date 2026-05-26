# Job Application Agent

A fully autonomous AI agent that searches job boards, evaluates listings, generates tailored cover letters, and submits applications — then emails you a daily HTML report of everything it did.

---

## How it works

```
Startup
  │
  ├── Export live CV from CV_URL → resume_generated.pdf (Playwright)
  ├── Login to each platform (LinkedIn, Reed, Adzuna, CV-Library, TotalJobs, Remotive, Arbeitnow)
  │
  └── OpenAI tool-calling agent loop (gpt-4o-mini)
        │
        ├── search_jobs × 7 platforms  →  new listings from each board
        ├── evaluate_job                →  GPT filter: relevant AI/ML role? experience OK?
        ├── generate_cover_letter       →  GPT-4o tailored letter (real details, no placeholders)
        └── apply_to_job
              ├── LinkedIn Easy Apply   →  browser-use AI form fill
              ├── External form         →  browser-use AI form fill → fallback to manual queue
              └── Reed / Easy Apply     →  native searcher apply()

End of cycle
  └── Daily summary email via Gmail SMTP
        ├── Auto-applied table   (title, company, source, status, timestamp, link)
        └── Manual queue cards   (pre-written cover letter included for each)
```

The agent runs on a configurable schedule (default: every 24 hours) via APScheduler and persists all state in a local SQLite database.

---

## Platforms covered

| Platform | Search | Auto-Apply |
|---|---|---|
| LinkedIn | Yes | Yes — Easy Apply via browser-use |
| Reed | Yes | Yes — Easy Apply |
| Adzuna | Yes (API or scrape) | Via browser-use |
| CV-Library | Yes | Via browser-use |
| TotalJobs | Yes | Via browser-use |
| Remotive | Yes | Via browser-use |
| Arbeitnow | Yes | Via browser-use |

---

## Evaluation filter

The GPT-4o-mini evaluator applies strict criteria before any application:

**Apply if:** AI Engineer · ML Engineer · Applied AI · LLM Engineer · GenAI Engineer · NLP Engineer · AI Research Engineer · Data Scientist (AI-focused)

**Skip if:**
- Role is not directly engineering AI/ML systems (sales, HR, product, ERP, finance…)
- Role requires more than 8 years of experience
- Same company already applied to in the current session

---

## Daily email report

After each cycle, a styled HTML email is sent to `NOTIFICATION_EMAIL` with:

- **Summary bar** — auto-applied count · manual queue count · failed count
- **Auto-applied table** — job title, company, source, location, status badge, timestamp, link
- **Manual queue cards** — one card per job with the pre-written cover letter ready to paste

---

## Setup

### Prerequisites

- Python 3.11+
- An OpenAI API key (GPT-4o access recommended)
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) enabled

### Install

```bash
git clone https://github.com/AyeniOluwatosinOlawale/job-application-agent.git
cd job-application-agent
pip install -r requirements.txt
playwright install chromium
```

### Environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# Gmail
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
NOTIFICATION_EMAIL=you@gmail.com

# Adzuna API (optional — falls back to browser scrape if omitted)
ADZUNA_APP_ID=
ADZUNA_APP_KEY=

# Your profile
APPLICANT_NAME=Your Name
APPLICANT_PHONE=+1-555-000-0000
CV_URL=https://your-cv-site.com/         # Must be printable as PDF
LINKEDIN_PROFILE_URL=https://linkedin.com/in/yourhandle
GITHUB_URL=https://github.com/yourhandle

# Search config
TARGET_ROLE=AI Engineer
TARGET_LOCATIONS=["Remote","London","New York"]
EXPERIENCE_YEARS=3

# Schedule (hours between runs)
RUN_INTERVAL_HOURS=24

# Anti-detection delays (seconds)
MIN_DELAY_SECONDS=2.0
MAX_DELAY_SECONDS=7.0
```

### LinkedIn session setup

LinkedIn requires an active browser session before the agent can scrape or apply.

```bash
python linkedin_setup.py
```

This opens a browser window for you to log in manually. The session cookies are saved for subsequent headless runs.

### Run

**One-shot (run immediately and exit):**
```bash
python main.py --once
```

**Scheduled (runs on startup then every `RUN_INTERVAL_HOURS`):**
```bash
python main.py
```

---

## Running as a system service

A setup script installs the agent as a `systemd` service so it survives reboots:

```bash
chmod +x install_service.sh setup.sh
./install_service.sh
```

Then manage it with:

```bash
sudo systemctl start job-agent
sudo systemctl status job-agent
journalctl -u job-agent -f
```

---

## Project structure

```
job-application-agent/
├── main.py                        # Entry point: scheduler, CV export, cycle runner
├── agent/
│   └── orchestrator.py            # OpenAI tool-calling agent loop + all tool handlers
├── applier/
│   └── browser_use_applier.py     # AI-powered form fill via browser-use
├── searchers/
│   ├── base.py                    # BaseSearcher (login, search, apply, teardown)
│   ├── linkedin.py
│   ├── reed.py
│   ├── adzuna.py
│   ├── cv_library.py
│   ├── totaljobs.py
│   ├── remotive.py
│   ├── arbeitnow.py
│   └── indeed.py / wellfound.py   # Additional searchers
├── models/
│   └── job.py                     # Job, Application, ApplicationStatus, JobSource
├── storage/
│   └── database.py                # SQLite via aiosqlite (jobs, applications, dedup)
├── notifier/
│   └── email_sender.py            # HTML email report via Gmail SMTP
├── config/
│   └── settings.py                # Pydantic settings (reads from .env)
├── logs/                          # Daily rotating log files
├── linkedin_setup.py              # One-time LinkedIn session setup
├── install_service.sh             # systemd service installer
└── .env.example
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `openai` | Tool-calling agent loop, job evaluation, cover letter generation |
| `playwright` | Headless Chromium for scraping and form submission |
| `browser-use` | AI-powered web form interaction |
| `langchain-openai` | LLM backend for browser-use |
| `apscheduler` | Interval-based job scheduler |
| `aiosqlite` | Async SQLite for job and application storage |
| `pydantic-settings` | Typed configuration from `.env` |
| `httpx` | Async HTTP for API-based searchers |
| `tenacity` | Retry logic for flaky network calls |
| `loguru` | Structured, coloured logging with daily log rotation |

---

## Anti-detection measures

- Randomised delays between actions (`MIN_DELAY_SECONDS` – `MAX_DELAY_SECONDS`)
- Chromium launched with `--disable-blink-features=AutomationControlled`
- Session-level company deduplication to avoid repeated hits on the same employer
- `--no-sandbox` and `--disable-dev-shm-usage` flags for stable headless operation

---

## License

MIT