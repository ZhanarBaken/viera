"""Thin clients for AmoCRM, WazzUp, Telegram. All I/O lives here."""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class AmoCRM:
    def __init__(self):
        self._base = f"https://{settings.AMOCRM_DOMAIN}/api/v4"
        self._headers = {
            "Authorization": f"Bearer {settings.AMOCRM_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        r = requests.get(f"{self._base}{path}", headers=self._headers, params=params, timeout=10)
        r.raise_for_status()
        return r.json()

    def _patch(self, path: str, data: dict) -> dict:
        r = requests.patch(f"{self._base}{path}", json=data, headers=self._headers, timeout=10)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data) -> dict:
        r = requests.post(f"{self._base}{path}", json=data, headers=self._headers, timeout=10)
        r.raise_for_status()
        return r.json()

    def get_lead_info(self, lead_id: str) -> dict:
        """Возвращает pipeline_id и status_id одним запросом."""
        data = self._get(f"/leads/{lead_id}")
        return {
            "pipeline_id": data.get("pipeline_id"),
            "status_id": str(data.get("status_id", "")),
        }

    def get_lead_pipeline_id(self, lead_id: str) -> int | None:
        return self.get_lead_info(lead_id)["pipeline_id"]

    def get_lead_status_id(self, lead_id: str) -> str | None:
        return self.get_lead_info(lead_id)["status_id"]

    def move_to_drip(self, lead_id: str):
        if settings.DRY_RUN:
            logger.info("[DRY_RUN] move_to_drip lead_id=%s", lead_id)
            return
        self._patch(f"/leads/{lead_id}", {
            "pipeline_id": settings.AMOCRM_PIPELINE_ID,
            "status_id": settings.AMOCRM_STAGE_DRIP_ID,
        })

    def move_to_human(self, lead_id: str):
        if settings.DRY_RUN:
            logger.info("[DRY_RUN] move_to_human lead_id=%s", lead_id)
            return
        self._patch(f"/leads/{lead_id}", {
            "pipeline_id": settings.AMOCRM_PIPELINE_ID,
            "status_id": settings.AMOCRM_STAGE_HUMAN_ID,
        })

    def close_lead(self, lead_id: str, note: str = "Не вышел на связь"):
        if settings.DRY_RUN:
            logger.info("[DRY_RUN] close_lead lead_id=%s note=%r", lead_id, note)
            return
        self._patch(f"/leads/{lead_id}", {"status_id": 143})
        self._post(f"/leads/{lead_id}/notes", [{"note_type": "common", "params": {"text": note}}])


class WazzUp:
    """WazzUp24 API client. Base URL: https://api.wazzup24.com"""

    _BASE = "https://api.wazzup24.com/v3"

    def __init__(self):
        self._headers = {
            "Authorization": f"Bearer {settings.WAZZUP_TOKEN}",
            "Content-Type": "application/json",
        }

    def send_message(self, phone: str, text: str, channel_id: str):
        if settings.DRY_RUN:
            logger.info("[DRY_RUN] send_message to=%s channel=%s text=%r", phone, channel_id, text)
            return
        r = requests.post(
            f"{self._BASE}/message",
            json={
                "channelId": channel_id,
                "chatType": "whatsapp",
                "chatId": "".join(c for c in phone if c.isdigit()),
                "text": text,
            },
            headers=self._headers,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def subscribe_webhooks(self, url: str):
        r = requests.patch(
            f"{self._BASE}/webhooks",
            json={
                "webhooksUri": url,
                "subscriptions": {
                    "messagesAndStatuses": True,
                },
            },
            headers=self._headers,
            timeout=10,
        )
        r.raise_for_status()  # 204 No Content — успех


class Telegram:
    def __init__(self):
        self._url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"

    def notify(self, text: str):
        requests.post(self._url, json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": text}, timeout=10)
