"""
POST /webhooks/wazzup/   — входящие сообщения от клиентов (WazzUp24)
POST /webhooks/amocrm/   — новые лиды + ответы менеджера (AmoCRM)
"""
import logging
from rest_framework.decorators import api_view
from rest_framework.response import Response
from . import services
from .redis_store import save_message

logger = logging.getLogger(__name__)


@api_view(["POST"])
def wazzup_webhook(request):
    data = request.data

    if data.get("test"):
        return Response({"ok": True})

    logger.debug("WazzUp webhook: %s", data)

    for message in data.get("messages", []):
        phone = _extract_phone(message)
        channel_id = message.get("channelId", "")
        if not phone:
            continue

        save_message(phone, message)

        if message.get("isEcho", False):
            services.on_outbound(phone, channel_id)
        else:
            services.on_inbound(phone, channel_id)

    return Response({"ok": True})


@api_view(["POST"])
def amocrm_webhook(request):
    """
    Два события из AmoCRM:
    - leads[add]  → новый лид создан
    - note[add] с note_type=10 → менеджер отправил исходящее сообщение клиенту
    """
    data = request.data
    logger.debug("AmoCRM webhook: %s", data)

    # Новый лид
    for lead in data.get("leads", {}).get("add", []):
        lead_id = str(lead.get("id", ""))
        phone = _extract_amo_phone(data)
        if lead_id and phone:
            services.on_new_lead(lead_id, phone)


    return Response({"ok": True})


def _extract_phone(message: dict) -> str:
    raw = message.get("contact", {}).get("phone") or message.get("chatId", "")
    return "".join(c for c in raw if c.isdigit())


def _extract_amo_phone(data: dict) -> str:
    for contact in data.get("contacts", {}).get("add", []):
        for field in contact.get("custom_fields", []):
            if field.get("code") == "PHONE":
                values = field.get("values", [])
                if values:
                    return "".join(c for c in values[0].get("value", "") if c.isdigit())
    return ""
