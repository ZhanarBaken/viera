from django.contrib import admin
from .models import AutomationConfig, ReminderMessage, LeadAutomation

admin.site.site_header = "Viera — Автоматизация продаж"
admin.site.site_title = "Viera CRM"
admin.site.index_title = "WhatsApp → AmoCRM: управление ботом"


@admin.register(AutomationConfig)
class AutomationConfigAdmin(admin.ModelAdmin):
    fieldsets = [
        ("Таймеры (все значения в минутах)", {
            "fields": [
                "manager_reply_wait",
                "first_reminder_delay",
                "second_reminder_delay",
                "close_delay",
                "reactivation_delay",
            ],
            "description": "1ч = 60 | 1ч40мин = 100 | 6ч = 360 | 24ч = 1440 | 7 дней = 10080",
        }),
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.http import HttpResponseRedirect
        from django.urls import reverse
        obj = AutomationConfig.get()
        return HttpResponseRedirect(
            reverse("admin:automation_automationconfig_change", args=[obj.pk])
        )


@admin.register(ReminderMessage)
class ReminderMessageAdmin(admin.ModelAdmin):
    list_display = ["stage", "short_content", "is_active"]
    list_filter = ["stage", "is_active"]
    list_editable = ["is_active"]

    @admin.display(description="Содержимое")
    def short_content(self, obj):
        if obj.text:
            return obj.text[:80] + "…" if len(obj.text) > 80 else obj.text
        if obj.image_url:
            name = obj.image_url.split("/")[-1]
            return f"🖼 {name}"
        return "—"


@admin.register(LeadAutomation)
class LeadAutomationAdmin(admin.ModelAdmin):
    list_display = ["lead_id", "phone", "chat_type", "status", "updated_at"]
    list_filter = ["status", "chat_type"]
    search_fields = ["lead_id", "phone"]
    readonly_fields = ["lead_id", "phone", "chat_type", "channel_id", "status", "task_id", "created_at", "updated_at"]

    def has_add_permission(self, request):
        return False
