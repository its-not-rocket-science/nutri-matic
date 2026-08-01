"""Outbound email — currently only the clinician-invite-by-email feature
(routers/clinician.py) sends anything. Plain stdlib smtplib rather than a
third-party email API: this repo's dependency list stays deliberately
short (see requirements.txt), and a real SMTP relay (the account's own
mail provider, or a transactional-email service's SMTP endpoint) is
enough for this app's actual volume — one invite email at a time, not a
marketing-send workload.

Configured entirely via env vars (SMTP_HOST/SMTP_PORT/SMTP_USERNAME/
SMTP_PASSWORD/EMAIL_FROM_ADDRESS), read the same way APP_ENV/SENTRY_DSN
are elsewhere in this app (see monitoring.py) — no config module, no
default that pretends to be a real mail server.

Deliberately NOT the same "no-op without credentials" convention
monitoring.py uses: Sentry is optional observability that can silently
do nothing when unconfigured without misleading anyone, but an invite
email that silently fails to send would leave a clinician believing
their client had been invited when nothing was ever delivered — the
opposite of this app's "don't fabricate success" rule elsewhere
(optimizer.py's cost handling, candidate_metadata.py's serving ranges).
send_email raises EmailNotConfigured instead, and callers must surface
that as a real error, not swallow it."""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText


class EmailNotConfigured(Exception):
    """Raised by send_email when SMTP_HOST isn't set — callers must turn
    this into a real error response, never a silent no-op, since sending
    the email is the entire point of the call site (see module docstring)."""


class EmailSendFailed(Exception):
    """Raised when SMTP is configured but the actual send failed (bad
    credentials, relay rejected the message, network error) — wraps the
    underlying smtplib exception so callers don't need to import smtplib
    themselves just to catch it."""


def send_email(to: str, subject: str, body_text: str) -> None:
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise EmailNotConfigured("SMTP_HOST is not set")
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    from_address = os.environ.get("EMAIL_FROM_ADDRESS", username or "")

    message = MIMEText(body_text)
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = to

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.sendmail(from_address, [to], message.as_string())
    except (smtplib.SMTPException, OSError) as e:
        raise EmailSendFailed(str(e)) from e
