"""
POST /webhooks/wazzup/   — входящие сообщения от клиентов (WazzUp24)
POST /webhooks/amocrm/   — новые лиды + ответы менеджера (AmoCRM)
"""
import logging
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response
from . import services
from .redis_store import save_message, is_bot_message
from .integrations import AmoCRM

logger = logging.getLogger(__name__)


@api_view(["POST"])
def wazzup_webhook(request):
    data = request.data

    if data.get("test"):
        return Response({"ok": True})

    logger.info("WazzUp webhook: %s", data)

    for status in data.get("statuses", []):
        logger.info(
            "WazzUp status: messageId=%s status=%s timestamp=%s",
            status.get("messageId"), status.get("status"), status.get("timestamp"),
        )

    for message in data.get("messages", []):
        chat_type = message.get("chatType", "whatsapp")
        if chat_type == "whatsgroup":
            # Групповые чаты не бывают лидами в AmoCRM — не заводим по ним записи вообще
            continue

        phone = _extract_phone(message)
        channel_id = message.get("channelId", "")
        logger.info(
            "WazzUp message: chatType=%s chatId=%s phone=%s status=%s isEcho=%s dateTime=%s",
            chat_type, message.get("chatId"), phone, message.get("status"),
            message.get("isEcho"), message.get("dateTime"),
        )
        if not phone:
            logger.warning(
                "WazzUp message skipped, no phone: chatType=%s chatId=%s contact=%s",
                chat_type, message.get("chatId"), message.get("contact"),
            )
            continue

        save_message(phone, message)
        client_name = message.get("contact", {}).get("name", "")
        wz_username = message.get("chatId", "") if chat_type == "instagram" else ""

        if message.get("isEcho", False):
            if is_bot_message(message.get("messageId")):
                logger.info("WazzUp echo of our own reminder, ignoring: messageId=%s", message.get("messageId"))
            else:
                services.on_outbound(phone, channel_id, chat_type)
        else:
            services.on_inbound(phone, channel_id, chat_type, client_name=client_name, wz_username=wz_username)

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
                    client_name = _amo_val(data, "message[add][0][author][name]")
                    services.on_new_lead(lead_id, phone=msg_talk_id, source="amocrm_instagram", amojo_talk_id=msg_talk_id, client_name=client_name, chat_type="instagram")
            elif msg_type == "outgoing":
                services.on_outbound_by_talk_id(msg_talk_id)
        else:
            logger.info("CHAT MESSAGE: origin=%s — ignoring (handled by WazzUp)", origin)
        return Response({"ok": True})

    # leads[update] — сделка изменена, в т.ч. статус (вручную менеджером или другой
    # автоматизацией AmoCRM). Судя по реальным вебхукам, статус приходит именно
    # под ключом "update", а не "status" — событие "leads[status]" тут не используется.
    update_lead_id = _amo_val(data, "leads[update][0][id]")
    if update_lead_id:
        new_status_id = _amo_val(data, "leads[update][0][status_id]")
        logger.info("leads[update]: lead_id=%s status_id=%s", update_lead_id, new_status_id)
        services.on_lead_status_changed(update_lead_id, new_status_id)
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

    crm = AmoCRM()

    # talk[add] — новый разговор WazzUp (приходит сразу при первом сообщении)
    talk_entity_id = _amo_val(data, "talk[add][0][entity_id]")
    talk_origin = _amo_val(data, "talk[add][0][origin]")
    if talk_entity_id and talk_origin.startswith("com.wazzup24"):
        lead_id = talk_entity_id
        logger.info("talk[add]: lead_id=%s origin=%s", lead_id, talk_origin)
        if "insta" in talk_origin:
            contact_id = _amo_val(data, "talk[add][0][contact_id]")
            username = crm.get_contact_instagram_username(contact_id) if contact_id else ""
            channel_id = crm.get_lead_wz_channel_id(lead_id)
            services.link_instagram_lead_id(lead_id, channel_id=channel_id, username=username)
        else:
            phone = crm.get_lead_phone(lead_id)
            if phone:
                linked = services.link_lead_id_by_phone(lead_id, phone)
                if not linked:
                    services.on_new_lead(lead_id, phone)
        return Response({"ok": True})

    # leads[add] — сделка создана напрямую (например SalesBot, без своего сообщения в чате)
    lead_add_id = _amo_val(data, "leads[add][0][id]")
    if lead_add_id:
        logger.info("leads[add]: lead_id=%s", lead_add_id)
        from .models import LeadAutomation
        if not LeadAutomation.objects.filter(lead_id=lead_add_id).exists():
            username = crm.get_lead_instagram_username(lead_add_id)
            channel_id = crm.get_lead_wz_channel_id(lead_add_id)
            linked = False
            if username or channel_id:
                linked = services.link_instagram_lead_id(lead_add_id, channel_id=channel_id, username=username)
            if not linked:
                phone = crm.get_lead_phone(lead_add_id)
                if phone:
                    linked = services.link_lead_id_by_phone(lead_add_id, phone)
                    if not linked:
                        services.on_new_lead(lead_add_id, phone)
        return Response({"ok": True})

    return Response({"ok": True})


def _amo_val(data: dict, key: str) -> str:
    """Извлечь скалярное значение из QueryDict-словаря."""
    raw = data.get(key)
    if raw is None:
        return ""
    return raw[0] if isinstance(raw, list) else raw



def _extract_phone(message: dict) -> str:
    """WhatsApp даёт номер в contact.phone или chatId. Instagram — не даёт
    телефона вообще, а chatId там обычно юзернейм (может случайно содержать
    цифры, например "sha1karovnaa"), поэтому для него берём contact.igsid —
    числовой Instagram-ID, а не пытаемся выковырять цифры из юзернейма.
    Иногда contact.igsid отсутствует, а chatId сам по себе уже чисто
    числовой (реальный igsid) — тогда используем его напрямую, это безопасно
    именно потому что проверяем "весь chatId — цифры", а не "есть цифры"."""
    contact = message.get("contact", {})
    if message.get("chatType") == "instagram":
        igsid = "".join(c for c in (contact.get("igsid") or "") if c.isdigit())
        if igsid:
            return igsid
        chat_id = message.get("chatId", "")
        return chat_id if chat_id.isdigit() else ""
    raw = contact.get("phone") or message.get("chatId", "")
    return "".join(c for c in raw if c.isdigit())
