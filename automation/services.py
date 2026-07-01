"""Business logic — вызывается из views, не знает про HTTP."""
from django.conf import settings
from .models import LeadAutomation, AutomationConfig
from .integrations import AmoCRM, WazzUp, Telegram
from . import tasks


def on_new_lead(lead_id: str, phone: str, source: str = LeadAutomation.WAZZUP, amojo_talk_id: str = "", client_name: str = ""):
    """Новый лид в AmoCRM — фиксируем, ничего не делаем."""
    LeadAutomation.objects.get_or_create(
        lead_id=lead_id,
        defaults={
            "phone": phone,
            "status": LeadAutomation.NEW,
            "source": source,
            "amojo_talk_id": amojo_talk_id,
            "client_name": client_name,
        },
    )


def _get_active_lead_by_talk_id(talk_id: str) -> "LeadAutomation | None":
    return (
        LeadAutomation.objects
        .filter(amojo_talk_id=talk_id)
        .exclude(status__in=[LeadAutomation.CLOSED, LeadAutomation.HUMAN])
        .order_by("-created_at")
        .first()
    )


def _get_active_lead(phone: str) -> LeadAutomation | None:
    return (
        LeadAutomation.objects
        .filter(phone=phone)
        .exclude(status__in=[LeadAutomation.CLOSED, LeadAutomation.HUMAN])
        .order_by("-created_at")
        .first()
    )


def _channel_name(lead: LeadAutomation) -> str:
    if lead.source == LeadAutomation.AMOCRM_INSTAGRAM:
        return "Viera Swim (Instagram Business)"
    return WazzUp().get_channel_name(lead.channel_id) if lead.channel_id else "неизвестен"


def _client_label(lead: LeadAutomation, phone: str = "") -> str:
    """Человекочитаемый идентификатор клиента для уведомлений."""
    if lead.client_name:
        return lead.client_name
    if lead.chat_type == LeadAutomation.WHATSAPP:
        return f"+{phone or lead.phone}"
    return ""  # WazzUp Instagram — нет полезного идентификатора


def _save_channel(lead: LeadAutomation, channel_id: str, chat_type: str = ""):
    fields = []
    if channel_id and not lead.channel_id:
        lead.channel_id = channel_id
        fields.append("channel_id")
    if chat_type and not lead.chat_type:
        lead.chat_type = chat_type
        fields.append("chat_type")
    if fields:
        lead.save(update_fields=fields)


def on_outbound_by_talk_id(talk_id: str):
    """Менеджер написал клиенту через AmoCRM Instagram DM."""
    lead = _get_active_lead_by_talk_id(talk_id)
    if lead is None or not lead.lead_id:
        return
    lead.cancel_pending_task()
    lead.status = LeadAutomation.WAITING
    config = AutomationConfig.get()
    task = tasks.check_client_response.apply_async(
        args=[lead.lead_id], countdown=config.manager_reply_wait * 60
    )
    lead.task_id = task.id
    lead.save()


def on_inbound_by_talk_id(talk_id: str):
    """Клиент написал через AmoCRM Instagram DM."""
    lead = (
        LeadAutomation.objects
        .filter(amojo_talk_id=talk_id)
        .exclude(status__in=[LeadAutomation.CLOSED, LeadAutomation.HUMAN, LeadAutomation.NEW])
        .order_by("-created_at")
        .first()
    )
    if lead is None:
        return

    if lead.status == LeadAutomation.WAITING:
        lead.cancel_pending_task()
        lead.status = LeadAutomation.NEW
        lead.save()
        return

    if lead.status == LeadAutomation.DRIP:
        crm = AmoCRM()
        info = crm.get_lead_info(lead.lead_id)
        if info["status_id"] != str(settings.AMOCRM_STAGE_DRIP_ID):
            return
        lead.cancel_pending_task()
        crm.move_to_human(lead.lead_id, phone=lead.phone)
        lead.status = LeadAutomation.HUMAN
        lead.save()
        channel_name = _channel_name(lead)
        client = _client_label(lead)
        Telegram().notify(
            f"💬 Клиент ответил!\n"
            + (f"Клиент: {client}\n" if client else "")
            + f"Лид: {lead.lead_id}\n"
            f"Канал: {channel_name}\n"
            f"Переведён в воронку «Нужен человек»"
        )


def on_outbound(phone: str, channel_id: str = "", chat_type: str = "whatsapp"):
    """Менеджер написал клиенту (WazzUp outbound) — запускаем таймер для активного лида."""
    lead = _get_active_lead(phone)
    if lead is None or not lead.lead_id:
        return

    _save_channel(lead, channel_id, chat_type)
    lead.cancel_pending_task()
    lead.status = LeadAutomation.WAITING

    config = AutomationConfig.get()
    task = tasks.check_client_response.apply_async(
        args=[lead.lead_id], countdown=config.manager_reply_wait * 60
    )
    lead.task_id = task.id
    lead.save()


def on_inbound(phone: str, channel_id: str = "", chat_type: str = "whatsapp", client_name: str = ""):
    """Клиент написал нам (WazzUp inbound) — ищем его активный лид."""
    lead = (
        LeadAutomation.objects
        .filter(phone=phone)
        .exclude(status__in=[LeadAutomation.CLOSED, LeadAutomation.HUMAN, LeadAutomation.NEW])
        .order_by("-created_at")
        .first()
    )
    if lead is None:
        return

    _save_channel(lead, channel_id, chat_type)
    if client_name and not lead.client_name:
        lead.client_name = client_name
        lead.save(update_fields=["client_name"])

    if lead.status == LeadAutomation.WAITING:
        lead.cancel_pending_task()
        lead.status = LeadAutomation.NEW
        lead.save()
        return

    if lead.status == LeadAutomation.DRIP:
        crm = AmoCRM()
        info = crm.get_lead_info(lead.lead_id)
        if info["status_id"] != str(settings.AMOCRM_STAGE_DRIP_ID):
            return
        lead.cancel_pending_task()
        crm.move_to_human(lead.lead_id, phone=lead.phone)
        lead.status = LeadAutomation.HUMAN
        lead.save()
        channel_name = _channel_name(lead)
        client = _client_label(lead, phone)
        Telegram().notify(
            f"💬 Клиент ответил!\n"
            + (f"Клиент: {client}\n" if client else "")
            + f"Лид: {lead.lead_id}\n"
            f"Канал: {channel_name}\n"
            f"Переведён в воронку «Нужен человек»"
        )
