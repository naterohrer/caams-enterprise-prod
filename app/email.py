"""Optional SMTP email connector for CAAMS.

SMTP settings are resolved in priority order:
  1. Database (site_settings row, id=1) — set via Admin → System → Email
  2. Environment variables — fallback for installs that pre-configure via env

If neither source provides CAAMS_SMTP_HOST (or smtp_host in DB) the module
degrades gracefully — functions return False and log a warning rather than
raising an error.

Environment variables (used when DB has no SMTP config):
  CAAMS_SMTP_HOST        — SMTP server hostname
  CAAMS_SMTP_FROM        — From address (e.g. caams@yourdomain.com)
  CAAMS_SMTP_PORT        — Port (default: 587)
  CAAMS_SMTP_USER        — SMTP username (leave blank for anonymous relay)
  CAAMS_SMTP_PASSWORD    — SMTP password
  CAAMS_SMTP_USE_TLS     — "true" (default) → STARTTLS; "false" → plain SMTP
  CAAMS_APP_BASE_URL     — Frontend base URL used to build invite links
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.crypto import decrypt_field
from app.logging_config import get_logger

log = get_logger("caams.email")

# Module-level env var defaults (used when DB has no SMTP config)
_ENV_SMTP_HOST = os.environ.get("CAAMS_SMTP_HOST", "")
_ENV_SMTP_PORT = int(os.environ.get("CAAMS_SMTP_PORT", "587"))
_ENV_SMTP_USER = os.environ.get("CAAMS_SMTP_USER", "")
_ENV_SMTP_PASSWORD = os.environ.get("CAAMS_SMTP_PASSWORD", "")
_ENV_SMTP_FROM = os.environ.get("CAAMS_SMTP_FROM", "")
_ENV_SMTP_USE_TLS = os.environ.get("CAAMS_SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")
APP_BASE_URL = os.environ.get("CAAMS_APP_BASE_URL", "").rstrip("/")


def _get_smtp_settings(db=None) -> dict:
    """Return effective SMTP settings, preferring DB config over env vars.

    Returns a dict with keys: host, port, user, password, from_addr,
    use_tls, source ('db' | 'env' | 'none').
    """
    row = None
    try:
        if db is not None:
            from app import models as _models
            row = db.query(_models.SiteSettings).filter(_models.SiteSettings.id == 1).first()
        else:
            from app.database import SessionLocal
            from app import models as _models
            _db = SessionLocal()
            try:
                row = _db.query(_models.SiteSettings).filter(_models.SiteSettings.id == 1).first()
            finally:
                _db.close()
    except Exception as exc:
        log.warning("Could not read SMTP settings from DB, using env vars: %s", exc)

    if row and row.smtp_host:
        return {
            "host": row.smtp_host,
            "port": row.smtp_port or 587,
            "user": row.smtp_user or "",
            "password": decrypt_field(row.smtp_password or ""),
            "from_addr": row.smtp_from or "",
            "use_tls": row.smtp_use_tls if row.smtp_use_tls is not None else True,
            "source": "db",
        }

    return {
        "host": _ENV_SMTP_HOST,
        "port": _ENV_SMTP_PORT,
        "user": _ENV_SMTP_USER,
        "password": _ENV_SMTP_PASSWORD,
        "from_addr": _ENV_SMTP_FROM,
        "use_tls": _ENV_SMTP_USE_TLS,
        "source": "env" if _ENV_SMTP_HOST else "none",
    }


def smtp_configured(db=None) -> bool:
    """Return True only if the minimum SMTP settings are present."""
    cfg = _get_smtp_settings(db)
    return bool(cfg["host"] and cfg["from_addr"])


def get_smtp_status(db=None) -> dict:
    """Return SMTP configuration status (password intentionally omitted)."""
    cfg = _get_smtp_settings(db)
    return {
        "configured": bool(cfg["host"] and cfg["from_addr"]),
        "host": cfg["host"] or None,
        "port": cfg["port"],
        "from_addr": cfg["from_addr"] or None,
        "user": cfg["user"] or None,
        "use_tls": cfg["use_tls"],
        "source": cfg["source"],
        "app_base_url": APP_BASE_URL or None,
    }


def _send_message(msg, cfg: dict) -> None:
    """Send a pre-built MIMEMultipart message using the provided config."""
    if cfg["use_tls"]:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if cfg["user"] and cfg["password"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.sendmail(cfg["from_addr"], msg["To"], msg.as_string())
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as smtp:
            smtp.ehlo()
            if cfg["user"] and cfg["password"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.sendmail(cfg["from_addr"], msg["To"], msg.as_string())


def send_test_email(to_email: str, db=None) -> tuple:
    """Send a test email to verify SMTP settings.

    Returns (success: bool, error: str).
    """
    cfg = _get_smtp_settings(db)
    if not (cfg["host"] and cfg["from_addr"]):
        return False, "SMTP is not configured (set CAAMS_SMTP_HOST and CAAMS_SMTP_FROM)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "CAAMS SMTP Test"
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_email
    msg.attach(MIMEText(
        "This is a test email from CAAMS to verify your SMTP configuration is working correctly.",
        "plain",
    ))
    msg.attach(MIMEText(
        "<p>This is a test email from <strong>CAAMS</strong> to verify your "
        "SMTP configuration is working correctly.</p>",
        "html",
    ))

    try:
        _send_message(msg, cfg)
        log.info("Test email sent to %s", to_email)
        return True, ""
    except Exception as exc:
        log.error("Failed to send test email to %s: %s", to_email, exc)
        return False, str(exc)


def build_invite_url(raw_token: str) -> str:
    """Return the full accept-invite URL for a given raw token, or '' if
    CAAMS_APP_BASE_URL is not set."""
    if not APP_BASE_URL:
        return ""
    return f"{APP_BASE_URL}/accept-invite?invite={raw_token}"


def send_invite_email(to_email: str, to_name: str, invite_url: str, db=None) -> bool:
    """Send an invite email to *to_email*.

    Returns True if the email was dispatched, False if SMTP is not configured
    or the send fails (error is logged but not re-raised).
    """
    cfg = _get_smtp_settings(db)
    if not (cfg["host"] and cfg["from_addr"]):
        log.info(
            "SMTP not configured — invite email not sent to %s "
            "(configure via Admin → System → Email or set CAAMS_SMTP_HOST)",
            to_email,
        )
        return False

    greeting = f"Hello {to_name}," if to_name else "Hello,"
    body_text = (
        f"{greeting}\n\n"
        "You have been invited to access CAAMS (Compliance and Auditing Made Simple).\n\n"
        "Click the link below to set your password and activate your account:\n\n"
        f"  {invite_url}\n\n"
        "This link expires in 72 hours.  If you did not expect this invitation "
        "you can safely ignore this email."
    )
    body_html = f"""\
<p>{greeting}</p>
<p>You have been invited to access <strong>CAAMS</strong>
   (Compliance and Auditing Made Simple).</p>
<p><a href="{invite_url}">Accept your invitation and set your password</a></p>
<p>Or copy this link into your browser:<br>
   <code>{invite_url}</code></p>
<p>This link expires in 72 hours.</p>
<p style="color:#888;font-size:0.85em;">
   If you did not expect this invitation you can safely ignore this email.
</p>
"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "You've been invited to CAAMS"
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        _send_message(msg, cfg)
        log.info("Invite email sent to %s", to_email)
        return True
    except Exception as exc:
        log.error("Failed to send invite email to %s: %s", to_email, exc)
        return False
