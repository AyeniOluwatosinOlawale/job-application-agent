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
  body {{ font-family: Arial, sans-serif; color: #1f2937; padding: 24px; }}
  h2 {{ color: #111827; }}
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
  .footer {{ color: #9ca3af; font-size: 11px; margin-top: 32px; }}
</style>
</head>
<body>
<h2>Job Application Summary &mdash; {date}</h2>
<div class="summary">
  Applied to <strong>{applied_count}</strong> positions &nbsp;|&nbsp;
  Searched <strong>{total_count}</strong> total &nbsp;|&nbsp;
  Failed: <strong>{failed_count}</strong>
</div>
<table>
  <thead>
    <tr>
      <th>Job Title</th>
      <th>Company</th>
      <th>Source</th>
      <th>Location</th>
      <th>Status</th>
      <th>Applied At</th>
      <th>Link</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
<p class="footer">Sent by AI Job Application Agent &bull; {timestamp}</p>
</body>
</html>
"""

ROW_TEMPLATE = """
<tr>
  <td>{title}</td>
  <td>{company}</td>
  <td>{source}</td>
  <td>{location}</td>
  <td><span class="badge" style="background:{status_color}">{status_label}</span></td>
  <td>{applied_at}</td>
  <td><a href="{url}" target="_blank">View</a></td>
</tr>
"""


class EmailSender:
    def __init__(self):
        self.smtp_host = "smtp.gmail.com"
        self.smtp_port = 587

    def send_daily_summary(self, applications: list[dict]) -> bool:
        if not applications:
            logger.info("No applications to report — skipping email.")
            return True

        applied = [a for a in applications if a.get("status") == "applied"]
        failed = [a for a in applications if a.get("status") == "failed"]

        rows = ""
        for app in applications:
            status = app.get("status", "unknown")
            applied_at_raw = app.get("applied_at") or ""
            try:
                applied_at = datetime.fromisoformat(applied_at_raw).strftime("%H:%M %d %b") if applied_at_raw else "—"
            except ValueError:
                applied_at = applied_at_raw

            rows += ROW_TEMPLATE.format(
                title=app.get("title", ""),
                company=app.get("company", ""),
                source=app.get("source", "").upper(),
                location=app.get("location", ""),
                status_color=STATUS_COLORS.get(status, "#6b7280"),
                status_label=status.upper().replace("_", " "),
                applied_at=applied_at,
                url=app.get("url", "#"),
            )

        body = HTML_TEMPLATE.format(
            date=datetime.now().strftime("%B %d, %Y"),
            applied_count=len(applied),
            total_count=len(applications),
            failed_count=len(failed),
            rows=rows,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        subject = (
            f"Job Applications — {datetime.now().strftime('%Y-%m-%d')} "
            f"({len(applied)} applied, {len(applications)} total)"
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
