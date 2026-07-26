"""Outbound email — the one place this product sends a message to a person.

There is exactly one caller class today (verification and password reset) and the module is
deliberately small enough to read in a minute, because everything it touches is security-critical:
a reset link in the wrong inbox is an account.

**Honest degradation, with one deliberate exception to the usual rule.** Everywhere else in this
codebase an unconfigured source degrades to "not connected" and the product carries on. Here the
degraded path *logs the link to the server log* instead, which is a real capability leak to anyone
who can read logs — so it is allowed only when `MAIL_DEV_ECHO=true` is explicitly set, and
`cli preflight` treats that flag being on as a production problem. Without it, an unconfigured
deployment simply fails to send and says so, which is the correct outcome: better a user who
cannot reset than a reset link in a log aggregator.

**The link never returns through the API.** `send()` reports whether delivery succeeded and
nothing else. A route that returned the token — even to "help testing" — would turn "I know your
email address" into "I own your account", and that shape is easy to add by accident.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("tradeos.mail")


def configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("MAIL_FROM"))


def dev_echo() -> bool:
    """Whether an unsendable message may be written to the log. Off unless explicitly enabled."""
    return os.environ.get("MAIL_DEV_ECHO", "").strip().lower() in ("1", "true", "yes")


def send(to: str, subject: str, body: str) -> bool:
    """Deliver one plain-text message. Returns whether it was actually sent.

    Plain text only, on purpose: an HTML mail is a rendering surface, and the two messages this
    product sends are a sentence and a link.
    """
    if not configured():
        if dev_echo():
            log.warning("MAIL NOT CONFIGURED — echoing to log (dev only)\nTo: %s\nSubject: %s\n%s",
                        to, subject, body)
        else:
            log.error("mail not configured; refusing to send %r to a user", subject)
        return False

    msg = EmailMessage()
    msg["From"] = os.environ["MAIL_FROM"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user, password = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")

    try:
        # STARTTLS on the submission port, implicit TLS on 465. There is no unencrypted path: a
        # message carrying a password-reset link does not travel in the clear even on a LAN.
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as s:
                if user:
                    s.login(user, password or "")
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls(context=ssl.create_default_context())
                if user:
                    s.login(user, password or "")
                s.send_message(msg)
        return True
    except Exception as exc:
        # Type only. An SMTP error can echo the envelope, and the envelope is the recipient.
        log.warning("mail delivery failed (%s)", type(exc).__name__)
        return False


def base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


VERIFY_SUBJECT = "Confirm your email address"
RESET_SUBJECT = "Reset your password"


# The token goes in the URL FRAGMENT, not the query string.
#
# A fragment is never transmitted to the server: it does not appear in the access log, in a proxy
# log, or in a Referer header. A query string appears in all three, and `GET /reset?token=...` in
# an access log is a working password reset sitting in a file that gets shipped to a log
# aggregator and kept for ninety days. Verified before the change — uvicorn logged exactly that.
#
# The single-page app reads `location.hash` and POSTs the token in a request body.

def verify_body(token: str) -> str:
    return (
        "Confirm this address to finish setting up your account:\n\n"
        f"{base_url()}/verify#token={token}\n\n"
        "The link is good for 24 hours and can be used once. If you did not create an account, "
        "you can ignore this — nothing happens until the link is opened.\n"
    )


def reset_body(token: str) -> str:
    return (
        "Someone asked to reset the password on this account. If it was you, use this link:\n\n"
        f"{base_url()}/reset#token={token}\n\n"
        "The link is good for one hour and can be used once. Opening it signs out every other "
        "session on the account.\n\n"
        "If it was not you, no action is needed — the password has not changed, and whoever asked "
        "did not learn anything about this account.\n"
    )
