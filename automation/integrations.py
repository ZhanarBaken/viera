"""Thin clients for AmoCRM, WazzUp, Telegram. All I/O lives here."""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _is_dry_run(phone: str = "") -> bool:
    """Возвращает True если нужен режим логирования (не слать реальные запросы)."""
    if not settings.DRY_RUN:
        return False
    clean = "".join(c for c in phone if c.isdigit())
    if clean and clean in settings.DRY_RUN_EXCEPTIONS:
        return False
    return True


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
        """Возвращает pipeline_id, status_id и responsible_user_id одним запросом."""
        data = self._get(f"/leads/{lead_id}")
        return {
            "pipeline_id": data.get("pipeline_id"),
            "status_id": str(data.get("status_id", "")),
            "responsible_user_id": data.get("responsible_user_id"),
        }

    def get_lead_pipeline_id(self, lead_id: str) -> int | None:
        return self.get_lead_info(lead_id)["pipeline_id"]

    def get_lead_status_id(self, lead_id: str) -> str | None:
        return self.get_lead_info(lead_id)["status_id"]

    def get_lead_talk_id(self, lead_id: str) -> str:
        """Получить amojo talk_id для лида через /talks endpoint."""
        try:
            data = self._get("/talks", params={"entity_id": lead_id, "entity_type": "leads", "limit": 250})
            for talk in data.get("_embedded", {}).get("talks", []):
                if str(talk.get("entity_id")) == str(lead_id) and talk.get("origin") == "instagram_business":
                    return str(talk.get("talk_id", ""))
        except Exception:
            logger.exception("AmoCRM get_lead_talk_id failed for lead_id=%s", lead_id)
        return ""

    def send_chat_message(self, talk_id: str, text: str, image_url: str = "", phone: str = ""):
        """Отправить сообщение в Instagram DM через AmoCRM Chat API."""
        if _is_dry_run(phone):
            logger.info("[DRY_RUN] send_chat_message talk_id=%s text=%r image_url=%s", talk_id, text, image_url)
            return
        payload = {}
        if text:
            payload["text"] = text
        if image_url:
            payload["attachment"] = {"type": "picture", "payload": {"url": image_url}}
        r = requests.post(
            f"{self._base}/talks/{talk_id}/messages",
            json=payload,
            headers=self._headers,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def get_lead_wz_channel_id(self, lead_id: str) -> str:
        """Получить WazzUp channel_id по WZ тегу на лиде."""
        try:
            data = self._get(f"/leads/{lead_id}")
            for tag in data.get("_embedded", {}).get("tags", []):
                name = tag.get("name", "")
                if name.startswith("WZ (") and name.endswith(")"):
                    return WazzUp().get_channel_id_by_name(name[4:-1])
        except Exception:
            logger.exception("get_lead_wz_channel_id failed for lead_id=%s", lead_id)
        return ""

    def get_lead_phone(self, lead_id: str) -> str:
        """Получить телефон клиента по lead_id через API (для повторных клиентов)."""
        try:
            data = self._get(f"/leads/{lead_id}", params={"with": "contacts"})
            contacts = data.get("_embedded", {}).get("contacts", [])
            if not contacts:
                return ""
            contact_id = contacts[0]["id"]
            contact = self._get(f"/contacts/{contact_id}")
            for field in contact.get("custom_fields_values") or []:
                if field.get("field_code") == "PHONE":
                    for v in field.get("values", []):
                        digits = "".join(c for c in str(v.get("value", "")) if c.isdigit())
                        if digits:
                            return digits
        except Exception:
            logger.exception("AmoCRM get_lead_phone failed for lead_id=%s", lead_id)
        return ""

    def move_to_drip(self, lead_id: str, phone: str = ""):
        if _is_dry_run(phone):
            logger.info("[DRY_RUN] move_to_drip lead_id=%s", lead_id)
            return
        self._patch(f"/leads/{lead_id}", {
            "pipeline_id": settings.AMOCRM_PIPELINE_ID,
            "status_id": settings.AMOCRM_STAGE_DRIP_ID,
        })

    def move_to_human(self, lead_id: str, phone: str = ""):
        if _is_dry_run(phone):
            logger.info("[DRY_RUN] move_to_human lead_id=%s", lead_id)
            return
        self._patch(f"/leads/{lead_id}", {
            "pipeline_id": settings.AMOCRM_PIPELINE_ID,
            "status_id": settings.AMOCRM_STAGE_HUMAN_ID,
        })

    def close_lead(self, lead_id: str, note: str = "Не вышел на связь", phone: str = ""):
        if _is_dry_run(phone):
            logger.info("[DRY_RUN] close_lead lead_id=%s note=%r", lead_id, note)
            return
        self._patch(f"/leads/{lead_id}", {"status_id": 143})
        self._post(f"/leads/{lead_id}/notes", [{"note_type": "common", "params": {"text": note}}])


_wazzup_channel_names: dict = {}  # кэш: channel_id → name


class WazzUp:
    """WazzUp24 API client. Base URL: https://api.wazzup24.com"""

    _BASE = "https://api.wazzup24.com/v3"

    def __init__(self):
        self._headers = {
            "Authorization": f"Bearer {settings.WAZZUP_TOKEN}",
            "Content-Type": "application/json",
        }

    def _load_channels(self):
        global _wazzup_channel_names
        if not _wazzup_channel_names:
            try:
                r = requests.get(f"{self._BASE}/channels", headers=self._headers, timeout=10)
                r.raise_for_status()
                _wazzup_channel_names = {
                    ch["channelId"]: ch.get("name", ch["channelId"])
                    for ch in r.json()
                    if "channelId" in ch
                }
            except Exception:
                logger.exception("WazzUp _load_channels failed")

    def get_channel_name(self, channel_id: str) -> str:
        self._load_channels()
        return _wazzup_channel_names.get(channel_id, channel_id)

    def get_channel_id_by_name(self, name: str) -> str:
        self._load_channels()
        for cid, cname in _wazzup_channel_names.items():
            if cname == name:
                return cid
        return ""

    def send_message(self, phone: str, text: str, channel_id: str, image_url: str = "", chat_type: str = "whatsapp"):
        if _is_dry_run(phone):
            logger.info("[DRY_RUN] send_message to=%s type=%s channel=%s text=%r image_url=%s", phone, chat_type, channel_id, text, image_url)
            return
        payload = {
            "channelId": channel_id,
            "chatType": chat_type,
            "chatId": "".join(c for c in phone if c.isdigit()),
        }
        if image_url:
            payload["contentUri"] = image_url
        if text:
            payload["text"] = text
        r = requests.post(f"{self._BASE}/message", json=payload, headers=self._headers, timeout=10)
        r.raise_for_status()
        result = r.json()
        from .redis_store import mark_bot_message
        mark_bot_message(result.get("messageId"))
        return result

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
