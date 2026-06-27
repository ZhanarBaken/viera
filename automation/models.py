import random
from django.db import models


class AutomationConfig(models.Model):
    """Singleton — все настройки таймингов в одном месте."""

    manager_reply_wait = models.PositiveIntegerField(
        default=20,
        verbose_name="Ожидание после ответа менеджера (мин)",
        help_text="Сколько минут ждать ответа клиента после того как менеджер написал",
    )
    first_reminder_delay = models.PositiveIntegerField(
        default=100,
        verbose_name="Задержка первого напоминания (мин)",
        help_text="1 час 40 минут = 100",
    )
    second_reminder_delay = models.PositiveIntegerField(
        default=360,
        verbose_name="Задержка второго напоминания (мин)",
        help_text="6 часов = 360. Отправляется только в 10:00–20:00 по Алматы, иначе откладывается до 10:00.",
    )
    close_delay = models.PositiveIntegerField(
        default=1440,
        verbose_name="Закрыть через N минут с момента создания лида",
        help_text="Сутки = 1440. Отсчёт идёт от момента когда лид впервые зафиксирован, не от последнего напоминания.",
    )
    reactivation_delay = models.PositiveIntegerField(
        default=10080,
        verbose_name="Задержка реактивации (мин)",
        help_text="7 дней = 10080",
    )

    class Meta:
        verbose_name = "Настройки автоматизации"
        verbose_name_plural = "Настройки автоматизации"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # нельзя удалить singleton

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ReminderMessage(models.Model):
    FIRST = "first"
    SECOND = "second"
    REACTIVATION = "reactivation"

    STAGE_CHOICES = [
        (FIRST, "Первое напоминание (через 1ч40мин)"),
        (SECOND, "Второе напоминание (через 6ч, только 10:00–20:00)"),
        (REACTIVATION, "Реактивация (через 7 дней)"),
    ]

    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, verbose_name="Этап")
    text = models.TextField(blank=True, verbose_name="Текст сообщения")
    image_url = models.URLField(blank=True, verbose_name="URL изображения")
    is_active = models.BooleanField(default=True, verbose_name="Активен")

    class Meta:
        verbose_name = "Шаблон напоминания"
        verbose_name_plural = "Шаблоны напоминаний"

    def __str__(self):
        return f"{self.get_stage_display()}: {self.text[:60]}…"

    @classmethod
    def random_for(cls, stage: str) -> "ReminderMessage | None":
        qs = cls.objects.filter(stage=stage, is_active=True)
        texts = list(qs.filter(image_url=""))
        images = list(qs.exclude(image_url=""))
        # Каждая группа (тексты и мемы) — один равнозначный слот
        pool = texts + ([random.choice(images)] if images else [])
        return random.choice(pool) if pool else None


class LeadAutomation(models.Model):
    NEW = "new"           # новый лид, менеджер ещё не писал
    WAITING = "waiting"   # менеджер написал, ждём ответа клиента
    DRIP = "drip"         # в воронке "Дожим бот"
    CLOSED = "closed"     # закрыт — не вышел на связь
    HUMAN = "human"       # клиент ответил — нужен человек

    STATUS_CHOICES = [
        (NEW, "Новый лид"),
        (WAITING, "Ожидание ответа клиента"),
        (DRIP, "Дожим бот"),
        (CLOSED, "Закрыт"),
        (HUMAN, "Нужен человек"),
    ]

    lead_id = models.CharField(max_length=50, unique=True, null=True, blank=True, verbose_name="ID лида AmoCRM")
    phone = models.CharField(max_length=50, db_index=True, verbose_name="Телефон клиента")
    channel_id = models.CharField(max_length=100, blank=True, verbose_name="ID канала WazzUp")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=WAITING, verbose_name="Статус")
    task_id = models.CharField(max_length=255, blank=True, verbose_name="ID задачи Celery")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")

    class Meta:
        verbose_name = "Автоматизация лида"
        verbose_name_plural = "Автоматизация лидов"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Lead {self.lead_id} | {self.phone} | {self.get_status_display()}"

    def cancel_pending_task(self):
        if self.task_id:
            from celery.app.control import revoke
            revoke(self.task_id, terminate=True)
            self.task_id = ""
