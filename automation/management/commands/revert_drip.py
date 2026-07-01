"""
Откатывает лиды из DRIP (Дожим бот) обратно в Новая заявка.
Находит все lead_ids которые мы отслеживаем в БД,
пересекает с теми что сейчас в Дожим бот в AmoCRM — это наши лиды.

Использование: python manage.py revert_drip
"""
from django.core.management.base import BaseCommand
import requests


class Command(BaseCommand):
    help = "Revert bot-moved DRIP leads back to Новая заявка"

    def handle(self, *args, **options):
        from django.conf import settings
        from automation.models import LeadAutomation
        from celery import current_app

        NEW_STAGE_ID = 75734750   # Новая заявка
        DRIP_STAGE_ID = 86780230  # Дожим бот
        PIPELINE_ID = settings.AMOCRM_PIPELINE_ID

        headers = {
            "Authorization": f"Bearer {settings.AMOCRM_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        base = f"https://{settings.AMOCRM_DOMAIN}/api/v4"

        # Все lead_ids которые наш бот отслеживает
        our_ids = set(
            LeadAutomation.objects
            .exclude(lead_id=None)
            .values_list("lead_id", flat=True)
        )
        self.stdout.write(f"Отслеживаем в БД: {len(our_ids)} лидов")

        # Все лиды в Дожим бот из AmoCRM
        drip_ids = []
        page = 1
        while True:
            r = requests.get(f"{base}/leads", headers=headers, params={
                "filter[pipeline_id]": PIPELINE_ID,
                "filter[status_id]": DRIP_STAGE_ID,
                "limit": 250, "page": page,
            }, timeout=15)
            if r.status_code == 204 or not r.content:
                break
            items = r.json().get("_embedded", {}).get("leads", [])
            if not items:
                break
            drip_ids += [str(i["id"]) for i in items]
            if len(items) < 250:
                break
            page += 1

        self.stdout.write(f"В Дожим бот (AmoCRM): {len(drip_ids)} лидов")

        # Пересечение — только наши лиды которые в Дожим бот
        to_revert = [lid for lid in drip_ids if lid in our_ids]
        self.stdout.write(f"Нужно откатить: {len(to_revert)}")

        ok = fail = 0
        for lead_id in to_revert:
            try:
                r = requests.patch(f"{base}/leads/{lead_id}", json={
                    "pipeline_id": PIPELINE_ID, "status_id": NEW_STAGE_ID,
                }, headers=headers, timeout=10)
                r.raise_for_status()

                lead = LeadAutomation.objects.filter(lead_id=lead_id).first()
                if lead:
                    if lead.task_id:
                        current_app.control.revoke(lead.task_id, terminate=True)
                    lead.status = LeadAutomation.NEW
                    lead.task_id = ""
                    lead.save(update_fields=["status", "task_id", "updated_at"])

                self.stdout.write(f"  ✓ {lead_id}")
                ok += 1
            except Exception as e:
                self.stdout.write(f"  ✗ {lead_id} error={e}")
                fail += 1

        self.stdout.write(f"\nГотово: {ok} откатано, {fail} ошибок")
