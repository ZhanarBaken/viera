from django.contrib import admin
from .models import AutomationConfig, ReminderMessage, LeadAutomation


@admin.register(AutomationConfig)
class AutomationConfigAdmin(admin.ModelAdmin):
    fieldsets = [
        ("Таймеры", {
            "fields": [
                "manager_reply_wait",
                "first_reminder_delay",
                "second_reminder_delay",
                "close_delay",
                "reactivation_delay",
            ],
            "description": "Все значения в минутах. 1ч = 60, 1ч40мин = 100, 5ч = 300, 7 дней = 10080.",
        }),
    ]

    def has_add_permission(self, request):
        return not AutomationConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReminderMessage)
class ReminderMessageAdmin(admin.ModelAdmin):
    list_display = ["stage", "short_text", "is_active"]
    list_filter = ["stage", "is_active"]
    list_editable = ["is_active"]

    @admin.display(description="Текст")
    def short_text(self, obj):
        return obj.text[:80] + "…" if len(obj.text) > 80 else obj.text


@admin.register(LeadAutomation)
class LeadAutomationAdmin(admin.ModelAdmin):
    list_display = ["lead_id", "phone", "status", "updated_at"]
    list_filter = ["status"]
    search_fields = ["lead_id", "phone"]
    readonly_fields = ["lead_id", "phone", "status", "task_id", "created_at", "updated_at"]

    def has_add_permission(self, request):
        return False
