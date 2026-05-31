from django.contrib import admin
from django.utils.html import format_html
from .models import DetectionLog, ChatHistory, UserYoloConfig, DetectionHistory

@admin.register(DetectionLog)
class DetectionLogAdmin(admin.ModelAdmin):
    # Added is_support_shared to list display to help admins understand visibility
    list_display = ("timestamp", "user", "person_count", "is_support_shared", "snapshot_preview")
    list_filter = ("timestamp", "is_support_shared")
    search_fields = ("person_count", "user__username")
    ordering = ("-timestamp",)

    def snapshot_preview(self, obj):
        # NEW LOGIC: Block image preview if the user hasn't shared it
        if not obj.is_support_shared:
            return format_html('<span style="color: #ef4444; font-weight: bold;">🔒 Private (User Only)</span>')
            
        if obj.snapshot:
            return format_html(
                '<img src="{}" width="120" style="border-radius:8px" />',
                obj.snapshot.url
            )
        return "No Image"

    snapshot_preview.short_description = "Snapshot"


@admin.register(ChatHistory)
class ChatHistoryAdmin(admin.ModelAdmin):
    list_display = ("user", "timestamp", "message_preview")
    list_filter = ("timestamp", "user")
    
    def message_preview(self, obj):
        return obj.message[:50] + "..." if len(obj.message) > 50 else obj.message
    message_preview.short_description = "Message"

@admin.register(UserYoloConfig)
class UserYoloConfigAdmin(admin.ModelAdmin):
    # Added subscription_tier so admins can manage user levels
    list_display = ("user", "subscription_tier", "conf_threshold", "iou_threshold", "save_annotations", "email_cooldown")
    list_editable = ("subscription_tier",) # Allows quick tier changes in the admin list view
    search_fields = ("user__username",)

@admin.register(DetectionHistory)
class DetectionHistoryAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "stats_summary", "is_video", "is_support_shared")
    list_filter = ("created_at", "is_video", "is_support_shared")
    search_fields = ("user__username", "stats_summary")