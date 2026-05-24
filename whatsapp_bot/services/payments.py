import hashlib
import hmac
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def verify_payment_signature(raw_body, signature):
    secret = settings.PAYMENT_WEBHOOK_SECRET
    if not secret:
        logger.warning("PAYMENT_WEBHOOK_SECRET is not configured; webhook signature verification is disabled.")
        return True
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature or "")


def parse_payment_payload(raw_body):
    payload = json.loads(raw_body.decode("utf-8") or "{}")
    data = payload.get("data") or payload
    status = str(data.get("status") or payload.get("status") or "").lower()
    reference = data.get("reference") or data.get("tx_ref") or data.get("flw_ref") or payload.get("reference")
    amount = data.get("amount") or payload.get("amount")
    gateway_reference = data.get("id") or data.get("transaction_id") or data.get("flw_ref") or ""
    return {
        "payload": payload,
        "status": status,
        "reference": str(reference or ""),
        "amount": amount,
        "gateway_reference": str(gateway_reference or ""),
    }
