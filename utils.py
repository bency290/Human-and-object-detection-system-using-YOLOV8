from django.core.mail import EmailMessage
from django.conf import settings
from django.utils import timezone

def send_detection_email(user_email, jpeg_bytes):
    """
    Sends an email with the annotated detection frame as an attachment[cite: 7, 17].
    """
    subject = f"Security Alert: Human Detected at {timezone.now().strftime('%H:%M:%S')}"
    body = "The YOLOv8 detection system has identified a person in your live feed[cite: 4, 16]."
    
    email = EmailMessage(
        subject,
        body,
        settings.EMAIL_HOST_USER,
        [user_email],
    )
    
    # Attach the image from the YOLO detection [cite: 12, 75]
    email.attach('detection.jpg', jpeg_bytes, 'image/jpeg')
    
    try:
        email.send()
        return True
    except Exception as e:
        print(f"Error sending email: {e}") [cite: 60]
        return False