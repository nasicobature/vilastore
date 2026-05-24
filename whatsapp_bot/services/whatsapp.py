import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class WhatsAppCloudClient:
    def __init__(self, access_token=None, phone_number_id=None):
        self.access_token = access_token or settings.WHATSAPP_ACCESS_TOKEN
        self.phone_number_id = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID

    @property
    def is_configured(self):
        return bool(self.access_token and self.phone_number_id)

    def send_text(self, to_phone, message):
        if not self.is_configured:
            logger.info("WhatsApp send skipped because API keys are not configured.", extra={"to": to_phone, "message": message})
            return {"configured": False, "sent": False}

        url = f"https://graph.facebook.com/v20.0/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        if response.status_code >= 400:
            logger.error("WhatsApp send failed.", extra={"status": response.status_code, "body": response.text})
        response.raise_for_status()
        return response.json()
