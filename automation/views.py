"""
POST /webhooks/wazzup/   — входящие сообщения от клиентов (WazzUp24)
POST /webhooks/amocrm/   — новые лиды + ответы менеджера (AmoCRM)
"""
import logging
from rest_framework.decorators import api_view
from rest_framework.response import Response
from . import services
from .redis_store import save_message
from .integrations import AmoCRM

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
        chat_type = message.get("chatType", "whatsapp")
        if not phone:
            continue

        save_message(phone, message)

        if message.get("isEcho", False):
            services.on_outbound(phone, channel_id, chat_type)
        else:
            services.on_inbound(phone, channel_id, chat_type)

    return Response({"ok": True})


@api_view(["POST"])
def amocrm_webhook(request):
    """
    AmoCRM шлёт form-encoded с PHP-стилем скобок: leads[add][0][id]=...
    DRF парсит это как плоский dict — используем _amo_* хелперы для извлечения.
    Также обрабатывает события чата amojo (входящие/исходящие сообщения Instagram Business).
    """
    data = dict(request.data)
    logger.info("=== AMOCRM WEBHOOK === keys=%s data=%s", list(data.keys()), data)

    # Сообщение в чате (message[add]) — срабатывает для всех каналов
    msg_talk_id = _amo_val(data, "message[add][0][talk_id]")
    if msg_talk_id:
        origin = _amo_val(data, "message[add][0][origin]")
        if origin == "instagram_business":
            msg_type = _amo_val(data, "message[add][0][type]")   # incoming / outgoing
            lead_id = _amo_val(data, "message[add][0][element_id]")
            logger.info("INSTAGRAM BUSINESS: talk_id=%s type=%s lead_id=%s", msg_talk_id, msg_type, lead_id)
            if msg_type == "incoming":
                from .models import LeadAutomation
                existing = LeadAutomation.objects.filter(amojo_talk_id=msg_talk_id).first()
                if existing:
                    services.on_inbound_by_talk_id(msg_talk_id)
                elif lead_id:
                    services.on_new_lead(lead_id, phone=msg_talk_id, source="amocrm_instagram", amojo_talk_id=msg_talk_id)
            elif msg_type == "outgoing":
                services.on_outbound_by_talk_id(msg_talk_id)
        else:
            logger.info("CHAT MESSAGE: origin=%s — ignoring (handled by WazzUp)", origin)
        return Response({"ok": True})

    # Менеджер написал клиенту в Instagram Business (talk[update] is_in_work=1)
    upd_talk_id = _amo_val(data, "talk[update][0][talk_id]")
    if upd_talk_id:
        origin = _amo_val(data, "talk[update][0][origin]")
        is_in_work = _amo_val(data, "talk[update][0][is_in_work]")
        if origin == "instagram_business" and is_in_work == "1":
            logger.info("INSTAGRAM BUSINESS manager reply: talk_id=%s", upd_talk_id)
            services.on_outbound_by_talk_id(upd_talk_id)
        return Response({"ok": True})

    # Новый лид (leads[add]) — WazzUp каналы
    crm = AmoCRM()
    for lead_id in _amo_lead_ids(data):
        phone = _amo_phone(data) or crm.get_lead_phone(lead_id)
        logger.info("AmoCRM new lead: lead_id=%s phone=%s", lead_id, phone or "(not found)")
        if phone:
            services.on_new_lead(lead_id, phone)

    return Response({"ok": True})


def _amo_val(data: dict, key: str) -> str:
    """Извлечь скалярное значение из QueryDict-словаря."""
    raw = data.get(key)
    if raw is None:
        return ""
    return raw[0] if isinstance(raw, list) else raw


def _amo_lead_ids(data: dict) -> list[str]:
    """Извлечь все id из leads[add][N][id]."""
    ids = []
    i = 0
    while True:
        raw = data.get(f"leads[add][{i}][id]")
        if raw is None:
            break
        # QueryDict может вернуть список если ключ встречается несколько раз
        val = raw[0] if isinstance(raw, list) else raw
        if val:
            ids.append(str(val))
        i += 1
    return ids


def _amo_phone(data: dict) -> str:
    """Извлечь телефон из contacts[add][N][custom_fields][M][values][0][value]."""
    i = 0
    while f"contacts[add][{i}][id]" in data:
        j = 0
        while f"contacts[add][{i}][custom_fields][{j}][code]" in data:
            raw_code = data.get(f"contacts[add][{i}][custom_fields][{j}][code]", "")
            code = raw_code[0] if isinstance(raw_code, list) else raw_code
            if code == "PHONE":
                raw_val = data.get(f"contacts[add][{i}][custom_fields][{j}][values][0][value]", "")
                val = raw_val[0] if isinstance(raw_val, list) else raw_val
                digits = "".join(c for c in val if c.isdigit())
                if digits:
                    return digits
            j += 1
        i += 1
    return ""


def _extract_phone(message: dict) -> str:
    raw = message.get("contact", {}).get("phone") or message.get("chatId", "")
    return "".join(c for c in raw if c.isdigit())
