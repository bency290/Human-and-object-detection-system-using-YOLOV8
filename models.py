from django.db import models
from django.conf import settings 
from django.utils import timezone
class ChatHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField()
    response = models.TextField()
    detection_occurred_at = models.CharField(max_length=100, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']
class UserYoloConfig(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='yolo_config')
    conf_threshold = models.FloatField(default=0.45) 
    iou_threshold = models.FloatField(default=0.45)
    save_annotations = models.BooleanField(default=True)
    target_classes = models.CharField(max_length=255, default="0", blank=True, help_text="Comma-separated YOLO class IDs")
    email_cooldown = models.IntegerField(default=5, help_text="Wait time in minutes between email alerts")

    def __str__(self):
        return f"{self.user.username}'s Config"
class DetectionHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='detections')
    media_file = models.FileField(upload_to='history/media/', null=True, blank=True) 
    is_video = models.BooleanField(default=False)
    stats_summary = models.CharField(max_length=255, help_text="e.g., '3 Persons, 1 Car'")
    json_data = models.JSONField(null=True, blank=True, help_text="Raw bounding box coordinates")
    created_at = models.DateTimeField(auto_now_add=True)
    is_support_shared = models.BooleanField(default=False, help_text="User explicitly shared this with admin support")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Detection by {self.user.username} on {self.created_at.strftime('%Y-%m-%d')}"
    
class DetectionLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True) 
    person_count = models.IntegerField(default=0)      
    snapshot = models.ImageField(upload_to="snapshots/", null=True, blank=True) 
    is_support_shared = models.BooleanField(default=False, help_text="User explicitly shared this snapshot with admin")
    
    # This stores the specific time of the last email sent
    last_email_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Detection @ {self.timestamp} | Persons: {self.person_count}"
    
class UserYoloConfig(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='yolo_config')
    conf_threshold = models.FloatField(default=0.45) 
    iou_threshold = models.FloatField(default=0.45)
    save_annotations = models.BooleanField(default=True)
    target_classes = models.CharField(max_length=255, default="0", blank=True, help_text="Comma-separated YOLO class IDs")
    
    # Resolves Conflict 1: Email Spam
    email_cooldown = models.IntegerField(default=5, help_text="Wait time in minutes between email alerts")

    # Resolves Conflict 3: Hardware Selection
    TIER_CHOICES = [
        ('FREE', 'Free Tier (CPU)'),
        ('PRO', 'Pro Tier (GPU/High-Res)'),
    ]
    subscription_tier = models.CharField(max_length=10, choices=TIER_CHOICES, default='FREE')

    # SaaS Logic for Hardware/Resolution
    def get_hardware_settings(self):
        if self.subscription_tier == 'PRO':
            return {"device": "0", "res": 1280}  # Pro gets GPU & High-Res
        return {"device": "cpu", "res": 640}     # Free gets CPU & Std-Res

    def __str__(self):
        return f"{self.user.username}'s Config ({self.subscription_tier})"