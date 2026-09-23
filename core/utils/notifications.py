import logging

import requests
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _send_email_via_resend(to_email: str, subject: str, message: str) -> bool:
    api_key = (getattr(settings, "RESEND_API_KEY", "") or "").strip()
    if not api_key:
        return False

    from_email = (
        getattr(settings, "RESEND_FROM_EMAIL", None)
        or getattr(settings, "DEFAULT_FROM_EMAIL", None)
        or getattr(settings, "EMAIL_HOST_USER", None)
    )
    if not from_email:
        raise ValueError("RESEND_FROM_EMAIL or DEFAULT_FROM_EMAIL must be configured.")

    api_url = (getattr(settings, "RESEND_API_URL", "") or "https://api.resend.com/emails").strip()
    timeout = int(getattr(settings, "EMAIL_TIMEOUT", 30) or 30)

    response = requests.post(
        api_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "text": message,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return True


def send_email(
    to_email: str,
    subject: str,
    message: str,
    fail_silently: bool = True,
    **kwargs,
) -> bool:
    if not to_email:
        return False

    try:
        if _send_email_via_resend(to_email, subject, message):
            logger.info("Email sent via Resend to %s", to_email)
            return True

        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)
        # Always raise internally so failures are caught below instead of being
        # swallowed by Django's own fail_silently handling in the SMTP backend.
        send_mail(subject, message, from_email, [to_email], fail_silently=False)
        logger.info("Email sent via SMTP to %s", to_email)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        if not fail_silently:
            raise
        return False


def send_sms(phone: str, message: str) -> bool:
    if not phone:
        return False

    backend = getattr(settings, "SMS_BACKEND", "console")

    if backend == "console":
        logger.info("SMS to %s: %s", phone, message)
        return True

    if backend == "http":
        url = getattr(settings, "SMS_WEBHOOK_URL", "")
        token = getattr(settings, "SMS_WEBHOOK_TOKEN", "")
        sender_id = getattr(settings, "SMS_SENDER_ID", "")

        if not url:
            logger.error("SMS_WEBHOOK_URL is not configured.")
            return False

        headers = {"Authorization": f"Bearer {token}"} if token else {}
        payload = {"to": phone, "message": message, "sender_id": sender_id}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            response.raise_for_status()
            return True
        except Exception:
            logger.exception("Failed to send SMS to %s", phone)
            return False

    logger.error("Unknown SMS_BACKEND: %s", backend)
    return False
