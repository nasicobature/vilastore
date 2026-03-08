import logging

import requests
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, message: str) -> bool:
    if not to_email:
        return False

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)
    try:
        send_mail(subject, message, from_email, [to_email], fail_silently=False)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
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
