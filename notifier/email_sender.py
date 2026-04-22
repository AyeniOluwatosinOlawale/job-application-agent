import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from config.settings import settings
from loguru import logger

STATUS_COLORS = {
    "applied": "#22c55e",
    "failed": "#ef4444",
    "skipped": "#f97316",
    "already_applied": "#6b7280",
    "pending": "#6b7280",
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; color: #1f2937; padding: 24px; max-width: 900px; margin: 0 auto; }}
  h2 {{ color: #111827; }}
  h3 {{ color: #374151; margin-top: 32px; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
  .summary {{ background: #f3f4f6; border-radius: 8px; padding: 12px 20px;
              margin-bottom: 20px; display: inline-block; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
  th {{ background: #1f2937; color: white; padding: 10px 14px;
        text-align: left; font-size: 13px; }}
  td {{ padding: 10px 14px; border-bottom: 1px solid #e5e7eb;
        font-size: 13px; vertical-align: top; }}
  tr:hover td {{ background: #f9fafb; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px;
            color: white; font-size: 11px; font-weight: bold; }}
  a {{ color: #2563eb; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .cover-letter {{ background: #f8fafc; border-left: 3px solid #2563eb;
                   padding: 10px 14px; font-size: 12px; color: #374151;
                   white-space: pre-wrap; margin-top: 6px; border-radius: 0 4px 4px 0; }}
  .manual-card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
                  padding: 16px; margin-bottom: 16px; }}
  .manual-card h4 {{ margin: 0 0 4px 0; color: #111827; }}
  .manual-card .meta {{ color: #6b7280; font-size: 12px; margin-bottom: 10px; }}
  .footer {{ color: #9ca3af; font-size: 11px; margin-top: 32px; }}
</style>
</head>
<body>
<h2>Job Application Report &mdash; {date}</h2>
<div class="summary">
  Auto-applied: <strong>{applied_count}</strong> &nbsp;|&nbsp;
  Manual queue: <strong>{manual_count}</strong> &nbsp;|&nbsp;
  Failed: <strong>{failed_count}</strong>
</div>

{auto_applied_section}

{manual_section}

<p class="footer">Sent by AI Job Application Agent &bull; {timestamp}</p>
</body>
</html>
"""

AUTO_TABLE = """
<h3>✅ Auto-Applied</h3>
<table>
  <thead>
    <tr>
      <th>Job Title</th><th>Company</th><th>Source</th>
      <th>Location</th><th>Status</th><th>Applied At</th><th>Link</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
"""

AUTO_ROW = """
<tr>
  <td>{title}</td><td>{company}</td><td>{source}</td>
  <td>{location}</td>
  <td><span class="badge" style="background:{status_color}">{status_label}</span></td>
  <td>{applied_at}</td>
  <td><a href="{url}" target="_blank">View</a></td>
</tr>
"""

MANUAL_CARD = """
<div class="manual-card">
  <h4><a href="{url}" target="_blank">{title}</a></h4>
  <div class="meta">{company} &bull; {location} &bull; {source}</div>
  <strong style="font-size:12px;">Cover Letter:</strong>
  <div class="cover-letter">{cover_letter}</div>
</div>
"""


class EmailSender:
    def __init__(self):
        self.smtp_host = "smtp.gmail.com"
        self.smtp_port = 587

    def send_daily_summary(self, applications: list[dict], manual_jobs: list[dict] = None) -> bool:
        manual_jobs = manual_jobs or []

        if not applications and not manual_jobs:
            logger.info("No applications to report — skipping email.")
            return True

        applied = [a for a in applications if a.get("status") == "applied"]
        failed = [a for a in applications if a.get("status") == "failed"]

        # Auto-applied section
        auto_section = ""
        if applications:
            rows = ""
            for app in applications:
                status = app.get("status", "unknown")
                applied_at_raw = app.get("applied_at") or ""
                try:
                    applied_at = datetime.fromisoformat(applied_at_raw).strftime("%H:%M %d %b") if applied_at_raw else "—"
                except ValueError:
                    applied_at = applied_at_raw

                rows += AUTO_ROW.format(
                    title=app.get("title", ""),
                    company=app.get("company", ""),
                    source=app.get("source", "").upper(),
                    location=app.get("location", ""),
                    status_color=STATUS_COLORS.get(status, "#6b7280"),
                    status_label=status.upper().replace("_", " "),
                    applied_at=applied_at,
                    url=app.get("url", "#"),
                )
            auto_section = AUTO_TABLE.format(rows=rows)
        else:
            auto_section = "<h3>✅ Auto-Applied</h3><p style='color:#6b7280'>No auto-applications today.</p>"

        # Manual apply section
        manual_section = ""
        if manual_jobs:
            cards = ""
            for job in manual_jobs:
                cover = (job.get("cover_letter") or "No cover letter generated.").replace("<", "&lt;").replace(">", "&gt;")
                cards += MANUAL_CARD.format(
                    title=job.get("title", ""),
                    company=job.get("company", ""),
                    location=job.get("location", ""),
                    source=job.get("source", "").upper(),
                    url=job.get("url", "#"),
                    cover_letter=cover,
                )
            manual_section = f"<h3>📋 Apply Manually — Top Matches ({len(manual_jobs)} jobs)</h3>{cards}"
        else:
            manual_section = ""

        body = HTML_TEMPLATE.format(
            date=datetime.now().strftime("%B %d, %Y"),
            applied_count=len(applied),
            manual_count=len(manual_jobs),
            failed_count=len(failed),
            auto_applied_section=auto_section,
            manual_section=manual_section,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        subject = (
            f"Jobs — {datetime.now().strftime('%d %b')} | "
            f"{len(applied)} auto-applied, {len(manual_jobs)} to review"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.gmail_address
        msg["To"] = settings.notification_email
        msg.attach(MIMEText(body, "html"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(settings.gmail_address, settings.gmail_app_password)
                server.sendmail(
                    settings.gmail_address,
                    settings.notification_email,
                    msg.as_string(),
                )
            logger.info(f"Email summary sent to {settings.notification_email}")
            return True
        except Exception as e:
            logger.error(f"Email failed: {e}")
            return False
