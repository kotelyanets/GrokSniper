"""
email_notifier.py
-----------------
Lightweight async email backup notification service.
Sends emails for critical events (trade closures, milestones) via SMTP.

Configuration (in .env):
    SMTP_HOST     — SMTP server (e.g. smtp.gmail.com)
    SMTP_PORT     — port (587 for TLS)
    SMTP_USER     — your email address
    SMTP_PASS     — app password (for Gmail: Settings → Security → App Passwords)
    NOTIFY_EMAIL  — recipient email

If SMTP_USER or NOTIFY_EMAIL are blank, all calls silently do nothing.
"""

import asyncio
import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("groksniper.email")

_SMTP_HOST    = os.getenv("SMTP_HOST",    "smtp.gmail.com")
_SMTP_PORT    = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER    = os.getenv("SMTP_USER",    "").strip()
_SMTP_PASS    = os.getenv("SMTP_PASS",    "").strip()
_NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "").strip()


async def send_email(subject: str, body: str) -> None:
    """
    Sends an HTML email asynchronously (in a thread pool so it won't block the event loop).
    Silently returns if SMTP is not configured.
    """
    if not _SMTP_USER or not _NOTIFY_EMAIL:
        return  # Not configured — skip silently

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_sync, subject, body)


def _send_sync(subject: str, body: str) -> None:
    """Blocking SMTP send — called from a thread pool via run_in_executor."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[GrokSniper] {subject}"
        msg["From"]    = _SMTP_USER
        msg["To"]      = _NOTIFY_EMAIL

        # Plain text fallback
        plain = body.replace("<b>", "").replace("</b>", "") \
                    .replace("<i>", "").replace("</i>", "") \
                    .replace("<br>", "\n")
        msg.attach(MIMEText(plain, "plain"))

        # HTML version
        html = f"""
        <html><body style="font-family: monospace; background: #0d0d0d; color: #e0e0e0; padding: 20px;">
        <h2 style="color:#00d4ff">🤖 GrokSniper AI</h2>
        <pre style="color:#e0e0e0">{body}</pre>
        </body></html>
        """
        msg.attach(MIMEText(html, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(_SMTP_USER, _SMTP_PASS)
            server.sendmail(_SMTP_USER, _NOTIFY_EMAIL, msg.as_string())

        logger.info(f"[Email] Sent: {subject} → {_NOTIFY_EMAIL}")
    except Exception as e:
        logger.warning(f"[Email] Failed to send '{subject}': {e}")
