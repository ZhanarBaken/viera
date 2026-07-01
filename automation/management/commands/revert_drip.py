"""
Откатывает лиды из DRIP (Дожим бот) обратно в Новая заявка.
Находит в нашей БД все LeadAutomation с status=DRIP обновлённые сегодня,
возвращает их в AmoCRM и сбрасывает наш статус на NEW.

Использование: python manage.py revert_drip
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = "Revert today's DRIP leads back to Новая заявка"

    def handle(self, *args, **options):
        from automation.models import LeadAutomation
        from automation.integrations import AmoCRM
        from celery.app import app_or_default

        NEW_STAGE_ID = 75734750  # Новая заявка
        cutoff = timezone.now() - timedelta(hours=24)

        leads = list(
            LeadAutomation.objects
            .filter(status=LeadAutomation.DRIP, updated_at__gte=cutoff)
            .exclude(lead_id=None)
        )
        self.stdout.write(f"Найдено DRIP лидов за сегодня: {len(leads)}")

        crm = AmoCRM()
        celery_app = app_or_default()
        ok = 0
        fail = 0

        for lead in leads:
            try:
                # Отменяем Celery задачу
                if lead.task_id:
                    celery_app.control.revoke(lead.task_id, terminate=True)

                # Возвращаем в AmoCRM
                crm._patch(f"/leads/{lead.lead_id}", {"status_id": NEW_STAGE_ID})

                # Сбрасываем статус в БД
                lead.status = LeadAutomation.NEW
                lead.task_id = ""
                lead.save(update_fields=["status", "task_id", "updated_at"])

                self.stdout.write(f"  ✓ lead_id={lead.lead_id} phone={lead.phone}")
                ok += 1
            except Exception as e:
                self.stdout.write(f"  ✗ lead_id={lead.lead_id} error={e}")
                fail += 1

        self.stdout.write(f"\nГотово: {ok} откатано, {fail} ошибок")
