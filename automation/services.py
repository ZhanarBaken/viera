"""Business logic — вызывается из views, не знает про HTTP."""
from django.conf import settings
from .models import LeadAutomation, AutomationConfig
from .integrations import AmoCRM, Telegram
from . import tasks


def on_new_lead(lead_id: str, phone: str):
    """Новый лид в AmoCRM — фиксируем, ничего не делаем."""
    LeadAutomation.objects.get_or_create(
        lead_id=lead_id,
        defaults={"phone": phone, "status": LeadAutomation.NEW},
    )


def _get_active_lead(phone: str) -> LeadAutomation | None:
    return (
        LeadAutomation.objects
        .filter(phone=phone)
        .exclude(status__in=[LeadAutomation.CLOSED, LeadAutomation.HUMAN])
        .order_by("-created_at")
        .first()
    )


def _save_channel(lead: LeadAutomation, channel_id: str):
    if channel_id and not lead.channel_id:
        lead.channel_id = channel_id
        lead.save(update_fields=["channel_id"])


def on_outbound(phone: str, channel_id: str = ""):
    """Менеджер написал клиенту (WazzUp outbound) — запускаем таймер для активного лида."""
    lead = _get_active_lead(phone)
    if lead is None or not lead.lead_id:
        return

    _save_channel(lead, channel_id)
    lead.cancel_pending_task()
    lead.status = LeadAutomation.WAITING

    config = AutomationConfig.get()
    task = tasks.check_client_response.apply_async(
        args=[lead.lead_id], countdown=config.manager_reply_wait * 60
    )
    lead.task_id = task.id
    lead.save()


def on_inbound(phone: str, channel_id: str = ""):
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

    _save_channel(lead, channel_id)

    if lead.status == LeadAutomation.WAITING:
        lead.cancel_pending_task()
        lead.status = LeadAutomation.NEW
        lead.save()
        return

    if lead.status == LeadAutomation.DRIP:
        crm = AmoCRM()
        if crm.get_lead_status_id(lead.lead_id) != str(settings.AMOCRM_STAGE_DRIP_ID):
            return
        lead.cancel_pending_task()
        crm.move_to_human(lead.lead_id)
        lead.status = LeadAutomation.HUMAN
        lead.save()
        Telegram().notify(
            f"💬 Клиент ответил!\n"
            f"Телефон: +{phone}\n"
            f"Лид: {lead.lead_id}\n"
            f"Переведён в воронку «Нужен человек»"
        )
