"""
Откатывает лиды из DRIP (Дожим бот) обратно в Новая заявка.
Берёт список из AmoCRM (stage=DRIP), а не из нашей БД.
Запуск: python manage.py shell < revert_drip_run.py
        (в Railway shell)
"""
import os
import requests
from celery import current_app

AMOCRM_DOMAIN = os.environ["AMOCRM_DOMAIN"]
AMOCRM_TOKEN = os.environ["AMOCRM_ACCESS_TOKEN"]
NEW_STAGE_ID = 75734750   # Новая заявка
DRIP_STAGE_ID = 86780230  # Дожим бот
PIPELINE_ID = 9461998

AMO_HEADERS = {
    "Authorization": f"Bearer {AMOCRM_TOKEN}",
    "Content-Type": "application/json",
}
AMO_BASE = f"https://{AMOCRM_DOMAIN}/api/v4"

# 1. Получить все лиды из AmoCRM в стадии Дожим бот
lead_ids = []
page = 1
while True:
    r = requests.get(
        f"{AMO_BASE}/leads",
        headers=AMO_HEADERS,
        params={
            "filter[pipeline_id]": PIPELINE_ID,
            "filter[status_id]": DRIP_STAGE_ID,
            "limit": 250,
            "page": page,
        },
        timeout=15,
    )
    if r.status_code == 204 or not r.content:
        break
    data = r.json()
    items = data.get("_embedded", {}).get("leads", [])
    if not items:
        break
    for item in items:
        lead_ids.append(str(item["id"]))
    if len(items) < 250:
        break
    page += 1

print(f"Найдено лидов в Дожим бот (AmoCRM): {len(lead_ids)}")

from automation.models import LeadAutomation

ok = 0
fail = 0

for lead_id in lead_ids:
    try:
        # Переместить в AmoCRM
        r = requests.patch(
            f"{AMO_BASE}/leads/{lead_id}",
            json={"pipeline_id": PIPELINE_ID, "status_id": NEW_STAGE_ID},
            headers=AMO_HEADERS,
            timeout=10,
        )
        r.raise_for_status()

        # Сбросить в нашей БД если есть
        lead = LeadAutomation.objects.filter(lead_id=lead_id).first()
        if lead:
            if lead.task_id:
                current_app.control.revoke(lead.task_id, terminate=True)
            lead.status = LeadAutomation.NEW
            lead.task_id = ""
            lead.save(update_fields=["status", "task_id", "updated_at"])

        print(f"  ✓ lead_id={lead_id}")
        ok += 1
    except Exception as e:
        print(f"  ✗ lead_id={lead_id} error={e}")
        fail += 1

print(f"\nГотово: {ok} откатано, {fail} ошибок")
