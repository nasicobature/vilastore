import logging
from dataclasses import dataclass
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class VTUResult:
    success: bool
    message: str
    provider_reference: str = ""
    raw: Optional[dict] = None


class VTUClient:
    def __init__(self, api_url=None, api_key=None):
        self.api_url = api_url or settings.VTU_API_URL
        self.api_key = api_key or settings.VTU_API_KEY

    @property
    def is_configured(self):
        return bool(self.api_url and self.api_key)

    def purchase_data(self, *, network, plan_code, recipient_phone, reference, amount):
        if not self.is_configured:
            logger.error("VTU API is not configured.", extra={"reference": reference})
            return VTUResult(False, "VTU API is not configured.", raw={"configured": False})

        payload = {
            "network": network,
            "plan_code": plan_code,
            "phone": recipient_phone,
            "reference": reference,
            "amount": str(amount),
        }
        try:
            response = requests.post(
                self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=30,
            )
            raw = response.json()
            success = response.ok and str(raw.get("status", "")).lower() in {"success", "successful", "completed", "ok"}
            return VTUResult(
                success=success,
                message=raw.get("message") or ("Data sent successfully." if success else "VTU request failed."),
                provider_reference=raw.get("reference") or raw.get("transaction_id") or "",
                raw=raw,
            )
        except Exception as exc:
            logger.exception("VTU API call failed.", extra={"reference": reference})
            return VTUResult(False, str(exc), raw={"error": str(exc)})
