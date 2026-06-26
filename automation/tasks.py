"""
Цепочка задач Celery. Каждая задача сама планирует следующую.
Статусы LeadAutomation защищают от двойного срабатывания.
"""
from celery import shared_task


def _get_lead(lead_id: str):
    from .models import LeadAutomation
    return LeadAutomation.objects.get(lead_id=lead_id)


def _schedule_next(lead, task_fn, delay_minutes: int):
    task = task_fn.apply_async(args=[lead.lead_id], countdown=delay_minutes * 60)
    lead.task_id = task.id
    lead.save(update_fields=["task_id", "updated_at"])


@shared_task
def check_client_response(lead_id: str):
    """Срабатывает через manager_reply_wait минут после ответа менеджера."""
    from django.conf import settings
    from .models import LeadAutomation, AutomationConfig
    from .integrations import AmoCRM

    lead = _get_lead(lead_id)
    if lead.status != LeadAutomation.WAITING:
        return

    crm = AmoCRM()

    # Двигаем только если лид ещё в разрешённых этапах (Неразобранное / Новая заявка)
    current_status = crm.get_lead_status_id(lead_id)
    if current_status not in settings.AMOCRM_ALLOWED_STAGE_IDS:
        lead.task_id = ""
        lead.save(update_fields=["task_id", "updated_at"])
        return

    crm.move_to_drip(lead_id)
    lead.status = LeadAutomation.DRIP
    config = AutomationConfig.get()
    _schedule_next(lead, send_first_reminder, config.first_reminder_delay)


def _is_in_drip(lead_id: str) -> bool:
    from django.conf import settings
    from .integrations import AmoCRM
    return AmoCRM().get_lead_status_id(lead_id) == str(settings.AMOCRM_STAGE_DRIP_ID)


@shared_task
def send_first_reminder(lead_id: str):
    from .models import LeadAutomation, AutomationConfig, ReminderMessage
    from .integrations import WazzUp

    lead = _get_lead(lead_id)
    if lead.status != LeadAutomation.DRIP:
        return
    if not _is_in_drip(lead_id):
        lead.task_id = ""
        lead.save(update_fields=["task_id", "updated_at"])
        return

    text = ReminderMessage.random_for(ReminderMessage.FIRST)
    if text:
        WazzUp().send_message(lead.phone, text, lead.channel_id)

    config = AutomationConfig.get()
    _schedule_next(lead, send_second_reminder, config.second_reminder_delay)


@shared_task
def send_second_reminder(lead_id: str):
    from .models import LeadAutomation, AutomationConfig, ReminderMessage
    from .integrations import WazzUp

    lead = _get_lead(lead_id)
    if lead.status != LeadAutomation.DRIP:
        return
    if not _is_in_drip(lead_id):
        lead.task_id = ""
        lead.save(update_fields=["task_id", "updated_at"])
        return

    text = ReminderMessage.random_for(ReminderMessage.SECOND)
    if text:
        WazzUp().send_message(lead.phone, text, lead.channel_id)

    # Закрываем ровно через close_delay минут с момента создания лида
    from django.utils import timezone
    from datetime import timedelta
    config = AutomationConfig.get()
    close_at = lead.created_at + timedelta(minutes=config.close_delay)
    countdown = max(0, (close_at - timezone.now()).total_seconds())
    task = close_lead.apply_async(args=[lead_id], countdown=countdown)
    lead.task_id = task.id
    lead.save(update_fields=["task_id", "updated_at"])


@shared_task
def close_lead(lead_id: str):
    from .models import LeadAutomation, AutomationConfig
    from .integrations import AmoCRM

    lead = _get_lead(lead_id)
    if lead.status != LeadAutomation.DRIP:
        return
    if not _is_in_drip(lead_id):
        lead.task_id = ""
        lead.save(update_fields=["task_id", "updated_at"])
        return

    AmoCRM().close_lead(lead_id)
    lead.status = LeadAutomation.CLOSED

    config = AutomationConfig.get()
    _schedule_next(lead, send_reactivation, config.reactivation_delay)


@shared_task
def send_reactivation(lead_id: str):
    from .models import LeadAutomation, ReminderMessage
    from .integrations import WazzUp

    from .models import LeadAutomation, ReminderMessage

    lead = _get_lead(lead_id)
    if lead.status != LeadAutomation.CLOSED:
        return

    # Если клиент уже написал снова — AmoCRM создал новый лид, не трогаем
    has_active_lead = LeadAutomation.objects.filter(
        phone=lead.phone,
        status__in=[LeadAutomation.NEW, LeadAutomation.WAITING, LeadAutomation.DRIP, LeadAutomation.HUMAN],
        created_at__gt=lead.created_at,
    ).exists()

    if has_active_lead:
        lead.task_id = ""
        lead.save(update_fields=["task_id", "updated_at"])
        return

    text = ReminderMessage.random_for(ReminderMessage.REACTIVATION)
    if text:
        WazzUp().send_message(lead.phone, text, lead.channel_id)

    lead.task_id = ""
    lead.save(update_fields=["task_id", "updated_at"])
