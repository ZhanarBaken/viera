"""
Цепочка задач Celery. Каждая задача сама планирует следующую.
Статусы LeadAutomation защищают от двойного срабатывания.
"""
from celery import shared_task


def _send_message(lead, msg):
    """Отправить сообщение клиенту через правильный канал."""
    from .models import LeadAutomation
    from .integrations import WazzUp, Telegram
    if lead.source == LeadAutomation.AMOCRM_INSTAGRAM:
        client = lead.client_name or "—"
        Telegram().notify(
            f"📨 Отправьте напоминание вручную в Viera Swim (Instagram)\n"
            f"Лид: {lead.lead_id}\n"
            f"Клиент: {client}\n\n"
            f"Текст:\n{msg.text}"
        )
    else:
        WazzUp().send_message(lead.phone, msg.text, lead.channel_id, image_url=msg.image_url, chat_type=lead.chat_type)


def _get_lead(lead_id: str):
    from .models import LeadAutomation
    return LeadAutomation.objects.get(lead_id=lead_id)


def _schedule_next(lead, task_fn, delay_minutes: int):
    task = task_fn.apply_async(args=[lead.lead_id], countdown=delay_minutes * 60)
    lead.task_id = task.id
    lead.save(update_fields=["task_id", "updated_at"])


def _close_at_eod(lead):
    """23:59 в день создания лида по Алматы (если создан после 19:00 — на следующий день)."""
    from django.utils import timezone
    from datetime import timedelta
    created_local = timezone.localtime(lead.created_at)
    close_day = created_local if created_local.hour < 19 else created_local + timedelta(days=1)
    return close_day.replace(hour=23, minute=59, second=0, microsecond=0)


def _seconds_until_window(hour_start: int = 10, hour_end: int = 21) -> int:
    """Возвращает 0 если сейчас в окне hour_start–hour_end (Алматы), иначе секунды до открытия."""
    from django.utils import timezone
    from datetime import timedelta

    now = timezone.localtime()  # переводим UTC → Asia/Almaty (TIME_ZONE из settings)
    if hour_start <= now.hour < hour_end:
        return 0
    if now.hour >= hour_end:
        next_open = (now + timedelta(days=1)).replace(
            hour=hour_start, minute=0, second=0, microsecond=0
        )
    else:
        next_open = now.replace(hour=hour_start, minute=0, second=0, microsecond=0)
    return max(0, int((next_open - now).total_seconds()))


@shared_task
def check_client_response(lead_id: str):
    """Срабатывает через manager_reply_wait минут после ответа менеджера."""
    from django.conf import settings
    from django.utils import timezone
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

    crm.move_to_drip(lead_id, phone=lead.phone)
    lead.status = LeadAutomation.DRIP
    lead.save(update_fields=["status", "updated_at"])
    config = AutomationConfig.get()
    _schedule_next(lead, send_first_reminder, config.first_reminder_delay)

    # Закрытие планируется сразу и не зависит от того, успели ли уйти напоминания —
    # close_lead сам проверит при срабатывании, что лид всё ещё в DRIP.
    close_at = _close_at_eod(lead)
    countdown = max(0, (close_at - timezone.now()).total_seconds())
    close_lead.apply_async(args=[lead_id], countdown=countdown)


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

    # Отправляем только в окне 10:00–21:00 по Алматы
    wait = _seconds_until_window()
    if wait > 0:
        task = send_first_reminder.apply_async(args=[lead_id], countdown=wait)
        lead.task_id = task.id
        lead.save(update_fields=["task_id", "updated_at"])
        return

    msg = ReminderMessage.random_for(ReminderMessage.FIRST)
    if msg:
        _send_message(lead, msg)

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

    # Отправляем только в окне 10:00–21:00 по Алматы
    wait = _seconds_until_window()
    if wait > 0:
        task = send_second_reminder.apply_async(args=[lead_id], countdown=wait)
        lead.task_id = task.id
        lead.save(update_fields=["task_id", "updated_at"])
        return

    msg = ReminderMessage.random_for(ReminderMessage.SECOND)
    if msg:
        _send_message(lead, msg)

    # Закрытие уже запланировано отдельно в check_client_response — здесь ничего не делаем
    lead.task_id = ""
    lead.save(update_fields=["task_id", "updated_at"])


@shared_task
def close_lead(lead_id: str):
    import random
    from datetime import timedelta
    from django.utils import timezone
    from .models import LeadAutomation, AutomationConfig
    from .integrations import AmoCRM

    lead = _get_lead(lead_id)
    if lead.status != LeadAutomation.DRIP:
        return
    if not _is_in_drip(lead_id):
        lead.task_id = ""
        lead.save(update_fields=["task_id", "updated_at"])
        return

    lead.cancel_pending_task()  # отменяем ещё не сработавшее напоминание, если оно есть
    AmoCRM().close_lead(lead_id, phone=lead.phone)
    lead.status = LeadAutomation.CLOSED

    # Реактивация — случайное время между 9:00 и 21:00 на 7-й день
    config = AutomationConfig.get()
    reactivation_day = timezone.localtime() + timedelta(minutes=config.reactivation_delay)
    total_minutes = random.randint(9 * 60, 21 * 60)
    send_at = reactivation_day.replace(
        hour=total_minutes // 60,
        minute=total_minutes % 60,
        second=0,
        microsecond=0,
    )
    countdown = max(0, (send_at - timezone.now()).total_seconds())
    task = send_reactivation.apply_async(args=[lead_id], countdown=countdown)
    lead.task_id = task.id
    lead.save(update_fields=["status", "task_id", "updated_at"])


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

    msg = ReminderMessage.random_for(ReminderMessage.REACTIVATION)
    if msg:
        _send_message(lead, msg)

    lead.task_id = ""
    lead.save(update_fields=["task_id", "updated_at"])
