from django.db import migrations


def update_first_reminder_delay(apps, schema_editor):
    AutomationConfig = apps.get_model("automation", "AutomationConfig")
    AutomationConfig.objects.filter(first_reminder_delay=100).update(first_reminder_delay=120)


class Migration(migrations.Migration):

    dependencies = [
        ("automation", "0007_add_client_name"),
    ]

    operations = [
        migrations.RunPython(update_first_reminder_delay, migrations.RunPython.noop),
    ]
