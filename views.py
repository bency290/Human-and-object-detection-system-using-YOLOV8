# =========================
# DJANGO IMPORTS
# =========================
from django.shortcuts import render, redirect
from django.http import StreamingHttpResponse, JsonResponse
from django.contrib.auth import (
    authenticate,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from .forms import VideoUploadForm
from .models import DetectionLog
from .yolo_video import process_video
from django.core.files.storage import default_storage
from django.conf import settings
from django.http import HttpResponse
from django.core.mail import send_mail
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
import os
import subprocess
import threading
import time
import csv
from django.core.mail import EmailMessage # Assuming standard Django email setup [cite: 60]
from django.utils import timezone
from groq import Groq
import datetime
from .models import UserYoloConfig, DetectionHistory
from .models import DetectionLog
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from collections import Counter
from django.core.files.base import ContentFile
from django.contrib.auth import get_user_model
from .models import ChatHistory
from datetime import timedelta
from .utils import send_detection_email
from django.core.mail import EmailMultiAlternatives
User = get_user_model()
_camera_lock = threading.Lock()

# =========================
# PYTHON / SYSTEM
# =========================
import json
import os
import threading
import time
import atexit
import base64
import numpy as np  # <--- CRITICAL: Added missing numpy import


# =========================
# OPENCV / TORCH / YOLO
# =========================
import cv2
import torch
from ultralytics import YOLO


# =========================
# PATHS & GLOBALS
# =========================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "detection", "yolo", "yolov8n.pt")

_model = None
_camera = None
_camera_lock = threading.Lock()
_current_user = None


# =========================
# LIVE DETECTION STATE
# =========================
CURRENT_PERSON_COUNT = 0
LAST_DETECTION_TIME = None
ALERT_MESSAGE = ""
LAST_LOG_TIME = 0          # prevents DB spam
LOG_INTERVAL = 5           # seconds

# =========================
# AUTH & ADMIN LOGIC
# =========================

# ==========================================
# AUTHENTICATION & REDIRECTION LOGIC
# ==========================================


@login_required
def toggle_user_status(request, user_id):
    """Admin only: Deactivate/Activate users."""
    if request.user.is_staff:
        target_user = get_object_or_404(User, id=user_id)
        if not target_user.is_superuser: # Protection for superusers
            target_user.is_active = not target_user.is_active
            target_user.save()
            status = "activated" if target_user.is_active else "deactivated"
            messages.success(request, f"User {target_user.username} has been {status}.")
    return redirect('admin_panel')
# =========================
# SINGLETON HELPERS
# =========================
# =========================
# SINGLETON HELPERS (Self-Healing)
# =========================
def get_model():
    global _model
    if _model is None:
        _model = YOLO(MODEL_PATH)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model.to(device)
    return _model

def get_persistent_camera():
    """
    Enhanced Singleton: Detects 'zombie' handles and force-reinitializes.
    This fixes the 'backend available but can't capture' error.
    """
    global _camera
    with _camera_lock:
        camera_is_dead = False
        if _camera is not None:
            success = _camera.grab() 
            if not success:
                print("⚠️ PERSISTENT CAMERA GHOSTED: Releasing stale handle...")
                _camera.release()
                camera_is_dead = True

        if _camera is None or camera_is_dead:
            print("🚀 INITIALIZING PERSISTENT CAMERA (Index 0)...")
            _camera = cv2.VideoCapture(0)
            
            if not _camera.isOpened():
                print("⚠️ Index 0 Failed, trying DSHOW...")
                _camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            _camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            _camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            _camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            time.sleep(2.0)    
        return _camera

@atexit.register
def release_camera():
    global _camera
    if _camera and _camera.isOpened():
        _camera.release()
        print("🛑 SYSTEM SHUTDOWN: Camera hardware released.")
# =========================
# AUTH & BASIC PAGES
# =========================


def home(request):
    """Landing page for the YOLOVISION system."""
    return render(request, "detection/home.html")

def login_user(request):
    """
    Handles user authentication and triggers the role-based 
    redirection logic upon successful login.
    """
    # 1. If user is already logged in, send them to the redirector immediately
    if request.user.is_authenticated:
        return redirect("dashboard_redirect")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        # 2. Basic validation
        if not username or not password:
            messages.error(request, "Please enter both username and password.")
            return render(request, "detection/login.html")

        # 3. Authenticate against the database
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            # 4. CRITICAL: Redirect to the 'Traffic Cop' instead of a hardcoded page
            return redirect("dashboard_redirect")
        
        # 5. Handle invalid credentials
        messages.error(request, "Invalid username or password.")

    return render(request, "detection/login.html")

@login_required
def dashboard_redirect(request):
    """
    THE TRAFFIC COP: 
    Determines if the logged-in user is an Admin (Staff) 
    or a Standard User and routes them accordingly.
    """
    if request.user.is_staff:
        # User is an Admin created via djangos admin panel or createsuperuser
        return redirect('admin_panel')
    else:
        # User is a standard registered user
        return redirect('dashboard')

@login_required
def logout_user(request):
    """Clears the session and logs the user out."""
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("login_user")

import re
from django.contrib import messages
from django.contrib.auth.models import User
from django.shortcuts import render, redirect


EMAIL_REGEX = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
PASSWORD_REGEX = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{8,}$"


# Updated Regex: At least 1 upper, 1 lower, 1 digit, 1 special char, 8+ total length
PASSWORD_REGEX = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&#])[A-Za-z\d@$!%*?&#]{8,}$"
EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

def register(request):
    if request.method == "POST":
        # 1. Collect and Clean Data
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm_password", "")

        # 2. Validation Checks
        if not username or not email or not password:
            messages.error(request, "All fields are required.")
            return redirect("register")

        if not re.match(EMAIL_REGEX, email):
            messages.error(request, "Enter a valid professional email address.")
            return redirect("register")

        # 3. Password Strength Check (The part that was likely failing)
        if not re.match(PASSWORD_REGEX, password):
            messages.error(
                request, 
                "Password must be 8+ characters and include uppercase, lowercase, a number, and a symbol (@$!%*?&#)."
            )
            return redirect("register")

        if password != confirm:
            messages.error(request, "Passwords do not match.")
            return redirect("register")

        # 4. Check for Existing User
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect("register")
            
        if User.objects.filter(email=email).exists():
            messages.error(request, "An account with this email already exists.")
            return redirect("register")

        # 5. Create User and Redirect
        try:
            User.objects.create_user(username=username, email=email, password=password)
            messages.success(request, "Account created successfully. Please login.")
            return redirect("login_user")
        except Exception as e:
            messages.error(request, f"An error occurred: {e}")
            return redirect("register")

    return render(request, "detection/register.html")





@login_required
def change_password(request):
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Password changed successfully")
            return redirect("profile")
    else:
        form = PasswordChangeForm(request.user)

    return render(
        request,
        "detection/change_password.html",
        {"form": form},
    )


@login_required
def reset_password(request):
    if request.method == "POST":
        password1 = request.POST.get("password1", "").strip()
        password2 = request.POST.get("password2", "").strip()

        # 1. Empty check
        if not password1 or not password2:
            messages.error(request, "All fields are required.")
            return redirect("reset_password")

        # 2. Match check
        if password1 != password2:
            messages.error(request, "Passwords do not match.")
            return redirect("reset_password")

        # 3. Length check
        if len(password1) < 8:
            messages.error(
                request,
                "Password must be at least 8 characters long."
            )
            return redirect("reset_password")

        # 4. Strength validations using regex
        if not re.search(r"[A-Z]", password1):
            messages.error(
                request,
                "Password must contain at least one uppercase letter."
            )
            return redirect("reset_password")

        if not re.search(r"[a-z]", password1):
            messages.error(
                request,
                "Password must contain at least one lowercase letter."
            )
            return redirect("reset_password")

        if not re.search(r"[0-9]", password1):
            messages.error(
                request,
                "Password must contain at least one number."
            )
            return redirect("reset_password")

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password1):
            messages.error(
                request,
                "Password must contain at least one special character."
            )
            return redirect("reset_password")

        # 5. Save new password
        user = request.user
        user.set_password(password1)
        user.save()

        messages.success(
            request,
            "Password reset successfully. Please log in again."
        )
        return redirect("login_user")

    return render(request, "detection/reset_password.html")
# =========================
# IMAGE UPLOAD DETECTION
# =========================

@login_required
def upload_detect(request):
    if request.method == "POST" and request.FILES.get("image"):
        image_file = request.FILES["image"]

        upload_path = os.path.join("media", "uploads")
        os.makedirs(upload_path, exist_ok=True)

        image_path = os.path.join(upload_path, image_file.name)
        with open(image_path, "wb+") as f:
            for chunk in image_file.chunks():
                f.write(chunk)

        model = get_model()
        img = cv2.imread(image_path)
        results = model(img, conf=0.25)

        annotated = results[0].plot()

        # --- 🚨 NEW: Extract Bounding Box Data for JSON ---
        json_data = []
        detected_names = []
        for box in results[0].boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            class_name = model.names[cls_id]
            detected_names.append(class_name)
            
            json_data.append({
                "class": class_name,
                "confidence": round(conf, 2),
                "coordinates": {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
            })

        # --- NEW: Create Summary ---
        person_count = detected_names.count("person")
        if detected_names:
            counts = {obj: detected_names.count(obj) for obj in set(detected_names)}
            stats_summary = ", ".join([f"{v} {k}(s)" for k, v in counts.items()])
        else:
            stats_summary = "No objects detected"

        # --- 🚨 NEW: Save to DetectionHistory for Profile Page ---
        config, _ = UserYoloConfig.objects.get_or_create(user=request.user)
        if config.save_annotations:
            _, img_encoded = cv2.imencode('.jpg', annotated)
            
            history = DetectionHistory.objects.create(
                user=request.user,
                is_video=False,
                stats_summary=stats_summary,
                json_data=json_data
            )
            history.media_file.save(
                f"detected_{request.user.username}_{history.id}.jpg", 
                ContentFile(img_encoded.tobytes())
            )
        # -----------------------------------------------------------

        # Legacy Log and Snapshot
        snapshot_path = None
        if person_count > 0:
            ts = time.strftime("%Y%m%d_%H%M%S")
            snapshot_path = f"snapshots/detect_{ts}.jpg"
            cv2.imwrite(
                os.path.join("media", snapshot_path),
                annotated
            )

            DetectionLog.objects.create(
                user=request.user,
                person_count=person_count,
                snapshot=snapshot_path,
            )
            if request.user.email:
                send_detection_alert(request.user.email, person_count, snapshot_path)

        return render(request,"detection/upload_result.html",
            {
                "count": person_count,
                "snapshot": snapshot_path,
            },
        )

    return render(request, "detection/upload.html")



def send_detection_email(user_email, annotated_frame):
    subject = "🚨 YOLOVISION LIVE ALERT: Person Detected!"
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")
    text_content = f"Alert: A person was detected on your live camera feed at {current_time}."

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.EMAIL_HOST_USER,
        to=[user_email]
    )

    # Convert the raw OpenCV frame directly to a JPEG in memory
    ret, buffer = cv2.imencode('.jpg', annotated_frame)
    if ret:
        # Attach the image bytes directly to the email
        msg.attach('live_alert.jpg', buffer.tobytes(), 'image/jpeg')

    # Send it!
    try:
        msg.send(fail_silently=False)
        print(f"✅ Email successfully delivered to {user_email}!")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
# =========================
# VIDEO STREAM (YOLO)
# =========================
def frame_generator():
    global CURRENT_PERSON_COUNT, LAST_DETECTION_TIME, ALERT_MESSAGE, LAST_LOG_TIME

    model = get_model()
    # Pull the persistent camera handle
    camera = get_persistent_camera()

    if camera is None or not camera.isOpened():
        print("❌ CRITICAL: Hardware is unreachable.")
        return

    try:
        while True:
            success, frame = camera.read()
            
            if not success:
                # Driver is busy or skipping a frame, wait and retry
                time.sleep(0.01)
                continue

            # Standardize for YOLO
            frame = cv2.resize(frame, (640, 480))
            
            # Fetch user-defined sensitivity
            user_config, _ = UserYoloConfig.objects.get_or_create(user=_current_user)

            # Inference
            results = model(
                frame, 
                conf=user_config.conf_threshold,
                iou=user_config.iou_threshold,
                verbose=False,
            )

            annotated = results[0].plot()
            
            # Detection Logic
            person_count = sum(1 for box in results[0].boxes if model.names[int(box.cls[0])] == "person")
            CURRENT_PERSON_COUNT = person_count
            now = timezone.now()

            if person_count > 0:
                LAST_DETECTION_TIME = now.strftime("%Y-%m-%d %H:%M:%S")
                ALERT_MESSAGE = f"⚠ {person_count} person(s) detected"

                # Email/Alerting Logic
                if _current_user:
                    last_log = DetectionLog.objects.filter(user=_current_user).exclude(last_email_sent_at__isnull=True).order_by('-last_email_sent_at').first()
                    
                    can_alert = True
                    if last_log and last_log.last_email_sent_at:
                        if now < last_log.last_email_sent_at + timedelta(minutes=user_config.email_cooldown):
                            can_alert = False

                    if can_alert:
                        send_detection_email(_current_user.email, annotated)
                        DetectionLog.objects.create(
                            user=_current_user,
                            person_count=person_count,
                            last_email_sent_at=now
                        )
                        print(f"📧 Persistent Alert Sent: {person_count} detected")
            else:
                ALERT_MESSAGE = ""

            # Encode and Stream
            ret, jpeg = cv2.imencode(".jpg", annotated)
            if not ret:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + jpeg.tobytes()
                + b"\r\n"
            )

    except (GeneratorExit, Exception) as e:
        # GeneratorExit happens when you click STOP or refresh
        print(f"📡 Stream Suspended: {type(e).__name__}")
    
    finally:
        # NOTE: We do NOT call camera.release() here.
        # We leave it open for the next session.
        print("✅ Hardware kept in 'WARM' state for immediate re-start.")
@login_required
def video_feed(request):
    """
    Streams the live webcam feed with YOLO detections to the dashboard.
    Sets the global _current_user so the frame_generator can log detections.
    """
    global _current_user
    _current_user = request.user

    return StreamingHttpResponse(
        frame_generator(),
        content_type="multipart/x-mixed-replace; boundary=frame",
    )

# =========================
# CHATBOT API
# =========================
@login_required
@csrf_exempt


# --- CHAT STREAM VIEW ---

def chat_stream(request):
    """
    Advanced AI Chatbot View: High-precision Ultralytics Persona with 
    Deep Analytical Reasoning and Professional Scannability.
    """
    if request.method != "POST":
        return HttpResponse("Invalid Method", status=405)

    try:
        # 1. AUTHENTICATE & LOAD API KEY
        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(PROJECT_ROOT, '.env')
        current_key = None
        try:
            with open(env_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if 'GROQ' in line and '=' in line:
                        current_key = line.split('=', 1)[1].strip().replace('"', '').replace("'", "")
        except Exception: pass

        if not current_key:
            return HttpResponse("Neural Node Error: API Key missing.", status=500)

      # 2. CONTEXT AGGREGATION
        data = json.loads(request.body)
        user_message = data.get("message", "")
        msg_lower = user_message.lower()
        live_count = data.get("live_context", {}).get("current_live_detections", 0)
        
        raw_historical = request.session.get('last_detection', "0")
        clean_visuals = raw_historical.replace("An image containing: ", "").strip()

        # 🚨 THE FIX: Pull in the Live Video global variable
        global LAST_DETECTION_TIME
        
        # Check Live Video first, then Image Uploads, then default to Not Recorded
        if LAST_DETECTION_TIME:
            detection_time = f"Live Camera Feed at {LAST_DETECTION_TIME}"
        elif request.session.get("last_detection_time"):
            detection_time = f"Static Image at {request.session.get('last_detection_time')}"
        else:
            detection_time = "Timestamp not recorded"


        # 3. HIGH-PRECISION PERSONA LOGIC
        is_requesting_optimization = any(word in msg_lower for word in ["yes", "optimize", "setup", "strategy", "sure", "want"])
        
        formatting_rules = """
        CRITICAL FORMATTING RULES:
        1. **Line Breaks**: You MUST use double line breaks (\n\n) between EVERY section, paragraph, list, and table. Never clump text together.
        2. **Headers**: Use Markdown headers (###) for new sections (e.g., ### 📊 Neural Workspace Status).
        3. **Lists**: Use bullet points (*) for object breakdowns and bold numbers (**1.**) for steps.
        4. **Data Tables**: If comparing data, use a clean Markdown table. Leave a blank line before and after the table.
        5. **Visual Cues**: Bold critical counts (e.g., **3 people**) and use emojis strategically (🚀, 📊, 🔍).
        """

        # 🚨 THE FIX: Inject the exact detection time into the Workspace State
        base_instructions = f"""
        You are Cambo Intelligence, a Vision AI expert specializing in Ultralytics YOLO. 🚀
        Mission: Deliver precise, expert analysis to maximize surveillance productivity. ✅

        WORKSPACE STATE:
        - **Live Detection**: {live_count} individuals.
        - **Static History**: {clean_visuals}.
        - **Last Detection Timestamp**: {detection_time}.
        - **Current Neural Clock**: {time.strftime('%H:%M:%S')}.
        
        If asked when an event occurred, explicitly state the 'Last Detection Timestamp'. Calculate how long ago it happened by comparing it to the 'Current Neural Clock'.
        """

        if is_requesting_optimization and "person" in clean_visuals:
            system_persona = base_instructions + formatting_rules + """
            The user wants a **Security Optimization Strategy**. 🔍
            - Output a structured report with bolded sections.
            - Provide a comparative table between current and historical occupancy.
            - Offer specific suggestions on YOLO sensitivity and persistence alerts.
            """
        else:
            system_persona = base_instructions + formatting_rules + """
            - Answer the user's query directly and immediately. Do not use greetings or conversational filler.
            - Maintain a helpful, intelligent, and highly capable tone. 
            - Create a distinct section for the 'Neural Workspace Log' to display data, then answer the user's specific questions.
            - Always end with a strategic question regarding the user's project goals separated by a blank line. ✅
            """

        # 4. NEURAL EXECUTION (GROQ API)
        client = Groq(api_key=current_key)
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_persona},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7, 
            max_tokens=800
        )
        
        # Get the actual text response from the AI
        bot_reply = completion.choices[0].message.content

        # 🚨 THE SECURE SAVE FIX 🚨
        # Make sure to import ChatHistory at the top of your views.py file!
        # from .models import ChatHistory
        
        if request.user.is_authenticated:
            ChatHistory.objects.create(
                user=request.user,                   # Locks this chat to the current user
                message=user_message,                # What the user typed
                response=bot_reply,                  # What the AI said
                detection_occurred_at=detection_time # Matches your model field
            )

        # Return the response back to the frontend
        return HttpResponse(bot_reply)

    except Exception as e:
        return HttpResponse(f"Neural Node Error: {str(e)}", status=500)

def save_yolo_detection(request):
    """
    This function saves the latest YOLO detection result
    in the user session so it can be accessed by the chatbot
    or dashboard interface.
    """
    current_time = datetime.datetime.now().strftime("%I:%M:%S %p") 
    

    request.session['last_detection'] = "An image containing: 1 person" 
    
   
    request.session['last_detection_time'] = current_time 
    
    request.session.modified = True 
    
    return HttpResponse("Detection saved successfully.")

@login_required
def dashboard(request):
    """
    Unified Dashboard: Handles Live Feed context, Image uploads, Video processing,
    AND saves results to the new DetectionHistory profile feature.
    """
    context = {
        "detected_image": None,
        "processed_video": None,
        "error": None,
        "person_count": 0,
    }
    if request.method == "POST":
        if request.FILES.get("image"):
            try:
                file_bytes = request.FILES["image"].read()
                np_arr = np.frombuffer(file_bytes, np.uint8)
                img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                model = get_model()
                results = model(img)
                annotated = results[0].plot()
                json_data = []
                for box in results[0].boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    class_name = model.names[cls_id]        
                    json_data.append({
                        "class": class_name,
                        "confidence": round(conf, 2),
                        "coordinates": {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
                    })
                # -----------------------------------------------------------

                detected_list = [model.names[int(box.cls[0])] for box in results[0].boxes]
                person_count = detected_list.count("person")
                context["person_count"] = person_count

                # Save session for chatbot context
                if detected_list:
                    counts = {obj: detected_list.count(obj) for obj in set(detected_list)}
                    detection_string = ", ".join([f"{v} {k}(s)" for k, v in counts.items()])
                    request.session["last_detection"] = f"An image containing: {detection_string}"
                    stats_summary = detection_string # Use this for our new history card!
                else:
                    request.session["last_detection"] = "No objects detected."
                    stats_summary = "No objects detected"
                
                # Capture and save the exact time
                current_time = datetime.datetime.now().strftime("%I:%M:%S %p")
                request.session["last_detection_time"] = current_time
                request.session.modified = True

                # --- 🚨 NEW: Save to DetectionHistory for Profile Page ---
                config, _ = UserYoloConfig.objects.get_or_create(user=request.user)
                if config.save_annotations:
                    # Convert the OpenCV annotated array back to bytes for Django to save
                    _, img_encoded = cv2.imencode('.jpg', annotated)
                    
                    history = DetectionHistory.objects.create(
                        user=request.user,
                        is_video=False,
                        stats_summary=stats_summary,
                        json_data=json_data
                    )
                    # Save the annotated image file to the database
                    history.media_file.save(
                        f"detected_{request.user.username}_{history.id}.jpg", 
                        ContentFile(img_encoded.tobytes())
                    )
                # -----------------------------------------------------------

                # Encode for display on the dashboard UI
                _, buffer = cv2.imencode(".jpg", annotated)
                context["detected_image"] = base64.b64encode(buffer).decode()

                # Save Legacy Log and Alert
                if person_count > 0:
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    snapshot_path = f"snapshots/detect_{ts}.jpg"
                    full_snapshot_path = os.path.join(settings.MEDIA_ROOT, snapshot_path)
                    os.makedirs(os.path.dirname(full_snapshot_path), exist_ok=True)
                    cv2.imwrite(full_snapshot_path, annotated)

                    DetectionLog.objects.create(person_count=person_count, snapshot=snapshot_path)
                    if request.user.email:
                        send_detection_alert(request.user.email, person_count, snapshot_path)

            except Exception as e:
                context["error"] = f"Image Processing Error: {str(e)}"

        # ================= 2. VIDEO UPLOAD LOGIC =================
        elif request.FILES.get("video"):
            try:
                video_file = request.FILES["video"]
                clean_name = video_file.name.replace(" ", "_")
                
                video_name = default_storage.save(f"videos/{clean_name}", video_file)
                input_path = default_storage.path(video_name)

                processed_rel_path = process_video(input_path)
                context["processed_video"] = settings.MEDIA_URL + processed_rel_path

            except Exception as e:
                context["error"] = f"Neural Video Error: {str(e)}"
                print(f"CRITICAL VIDEO ERROR: {e}")

    return render(request, "detection/dashboard.html", context)


def process_video(input_path):
    model = get_model()
    video_filename = os.path.basename(input_path)
    output_dir = os.path.join(settings.MEDIA_ROOT, 'videos', 'predict_temp')
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. OPTIMIZED INFERENCE
    results = model.predict(
        source=input_path, 
        stream=True,     # Memory efficiency
        save=True,       # Render boxes
        conf=0.25, 
        imgsz=320,       # <--- SPEED TRICK: Lower resolution (Standard is 640)
        vid_stride=2,    # <--- SPEED TRICK: Skip every other frame (50% faster)
        project=output_dir, 
        name='current', 
        exist_ok=True,
        verbose=False
    )

    # Trigger the generator
    for _ in results:
        pass  

    yolo_output_path = os.path.join(output_dir, 'current', video_filename)
    final_video_name = f"fast_{video_filename}"
    final_output_path = os.path.join(settings.MEDIA_ROOT, 'videos', final_video_name)

    # 2. OPTIMIZED ENCODING
    # '-preset ultrafast' is the fastest possible conversion setting
    ffmpeg_cmd = [
        'ffmpeg', '-y', '-i', yolo_output_path,
        '-vcodec', 'libx264', '-crf', '32', 
        '-preset', 'ultrafast', # <--- SPEED TRICK: Fastest encoding
        '-threads', '0',        # Use all CPU cores
        final_output_path
    ]
    
    subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
    return f"videos/{final_video_name}"
  
def test_email(request):
    send_mail(
        "Test Alert",
        "Your system is working!",
        "sonamary290@gmail.com",
        ["sonamary290@gmail.com"], 
        fail_silently=False,
    )
    
    # THIS is the missing piece that fixes your ValueError!
    return HttpResponse("✅ Email sent successfully! Check your inbox.")


def send_detection_alert(user_email, person_count, snapshot_path):
    subject = f"🚨 YOLOVISION ALERT: {person_count} Person(s) Detected!"
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. HTML Email Template Generation
    html_content = render_to_string("detection/email_alert.html", {
        "person_count": person_count,
        "time": current_time
    })
    
    text_content = f"Alert: {person_count} person(s) detected by YOLOVISION at {current_time}."
    
    # 2. Build the Email
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.EMAIL_HOST_USER,
        to=[user_email]
    )
    msg.attach_alternative(html_content, "text/html") 
    # 3. Attachment Handling (The Annotated Screenshot)
    full_path = os.path.join(settings.BASE_DIR, "media", snapshot_path) 
    
    if os.path.exists(full_path):
        with open(full_path, 'rb') as f:
            # attach(filename, file_content, mimetype)
            msg.attach(os.path.basename(full_path), f.read(), 'image/jpeg')

    # Send it!
    try:
        msg.send(fail_silently=False)
        print("Alert email sent successfully.")
    except Exception as e:
        print(f"Failed to send alert: {e}")



# 1. Setup API Key (get yours at console.groq.com)
os.environ["GROQ_API_KEY"] = "your_groq_api_key_here"

class VisionAssistant:
    def __init__(self, model_path="yolo11n.pt"):
        self.yolo_model = YOLO(model_path)
        self.groq_client = Groq()
        self.current_context = ""

    def update_context(self, frame):
        """Processes a frame and updates the visual context string."""
        results = self.yolo_model(frame, verbose=False)
        
        # Extract object names and counts
        detections = results[0].boxes.cls.tolist()
        names = results[0].names
        found_objects = [names[int(cls)] for cls in detections]
        
        if found_objects:
            obj_counts = {obj: found_objects.count(obj) for obj in set(found_objects)}
            self.current_context = ", ".join([f"{count} {obj}(s)" for obj, count in obj_counts.items()])
        else:
            self.current_context = "no objects detected"

    def ask_chatbot(self, user_query):
        """Sends context + query to Groq for a fast response."""
        system_prompt = (
            f"You are an AI assistant for a smart surveillance system. "
            f"Currently, the camera sees: {self.current_context}. "
            "Answer the user's question based on this context concisely."
        )

        completion = self.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            temperature=0.5,
            max_tokens=150
        )
        return completion.choices[0].message.content


    
@login_required  # <-- Make sure you have the @ symbol here!
def get_chat_history(request):
    # This perfectly filters the database to only return the current user's chats
    chats = ChatHistory.objects.filter(user=request.user).values(
        'message', 
        'response', 
        'timestamp', 
        'detection_occurred_at'
    )
    
    return JsonResponse(list(chats), safe=False)

# ==========================================
# USER PROFILE & CONFIGURATION
# ==========================================
@login_required
def profile(request):
    """Handles personal info updates and YOLO sensitivity settings."""
    config, _ = UserYoloConfig.objects.get_or_create(user=request.user)
    recent_history = DetectionHistory.objects.filter(user=request.user).order_by('-created_at')[:4]

    if request.method == "POST":
        if 'update_profile' in request.POST:
            user = request.user
            user.username = request.POST.get("username", user.username)
            user.email = request.POST.get("email", user.email)
            user.save()
            messages.success(request, "Personal credentials updated successfully.")
            return redirect("profile")

        elif 'update_yolo_config' in request.POST:
            # Scale 0-100 input back to 0.0-1.0 for YOLO
            config.conf_threshold = float(request.POST.get('conf_threshold', 45)) / 100.0
            config.iou_threshold = float(request.POST.get('iou_threshold', 45)) / 100.0
            config.save_annotations = request.POST.get('save_annotations') == 'on'
            config.save()
            messages.success(request, "YOLO parameters updated successfully.")
            return redirect("profile")

    context = {
        'config': config,
        'recent_history': recent_history,
        'conf_display': int(config.conf_threshold * 100),
        'iou_display': int(config.iou_threshold * 100),
    }
    return render(request, "detection/profile.html", context)


# ==========================================
# ADMIN COMMAND CENTER
# ==========================================
@login_required
def admin_panel(request):
    """Monitoring dashboard for Admins to view users and global logs."""
    if not request.user.is_staff:
        messages.error(request, "Access Denied: Admin Privileges Required.")
        return redirect('dashboard')

    # Monitor all users and their activity
    all_users = User.objects.all().order_by('-date_joined')
    
    # Review latest 20 visual snapshots
    logs = DetectionLog.objects.exclude(snapshot='').order_by('-timestamp')[:20]

    return render(request, 'detection/admin_panel.html', {
        'users': all_users,
        'logs': logs,
    })


@login_required
def toggle_user_status(request, user_id):
    """Admin feature to activate/deactivate standard users."""
    if request.user.is_staff:
        target_user = get_object_or_404(User, id=user_id)
        if not target_user.is_superuser:
            target_user.is_active = not target_user.is_active
            target_user.save()
            status = "enabled" if target_user.is_active else "disabled"
            messages.info(request, f"User {target_user.username} has been {status}.")
    return redirect('admin_panel')


# ==========================================
# DATA EXPORT & DOWNLOADS
# ==========================================
@login_required
def download_detection_json(request, detection_id):
    """Allows users to download raw bounding box data for a specific detection."""
    detection = get_object_or_404(DetectionHistory, id=detection_id, user=request.user)

    if not detection.json_data:
        raise Http404("No raw data available for this detection.")

    json_string = json.dumps(detection.json_data, indent=4)
    response = HttpResponse(json_string, content_type='application/json')
    response['Content-Disposition'] = f'attachment; filename="yolo_raw_data_{detection.id}.json"'
    return response


# ==========================================
# ADMIN PANEL VIEW
# ==========================================
@login_required
def admin_panel(request):
    """Monitoring dashboard for Admins."""
    if not request.user.is_staff:
        messages.error(request, "Access Denied.")
        return redirect('dashboard')

    # 1. Filter: Exclude the Admin/Superusers from the list
    all_users = User.objects.filter(is_staff=False).order_by('-date_joined')
    
    # 2. Latest 20 visual snapshots
    logs = DetectionLog.objects.exclude(snapshot='').order_by('-timestamp')[:20]

    return render(request, 'detection/admin_panel.html', {
        'users': all_users,
        'logs': logs,
    })

# ==========================================
# EXPORT LOGS (Fixed NameError & Logic)
# ==========================================
@login_required
def export_detection_logs(request):
    """Generates a downloadable CSV report of system detections."""
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=401)

    response = HttpResponse(content_type='text/csv')
    date_str = timezone.now().strftime("%Y-%m-%d")
    response['Content-Disposition'] = f'attachment; filename="YOLO_System_Logs_{date_str}.csv"'

    writer = csv.writer(response)
    # Header Row
    writer.writerow(['Log ID', 'Timestamp', 'Person Count', 'Operator Status', 'Snapshot URL'])

    # Get all logs
    logs = DetectionLog.objects.all().order_by('-timestamp')
    
    for log in logs:
        # --- FIX: Safe check for 'user' attribute ---
        if hasattr(log, 'user') and log.user:
            op_name = log.user.username
        else:
            op_name = "System/Live Feed" # Default if no user linked
        
        # Safe URL generation
        try:
            image_url = request.build_absolute_uri(log.snapshot.url) if log.snapshot else "No Image"
        except Exception:
            image_url = "URL Error"

        writer.writerow([
            log.id, 
            log.timestamp.strftime("%Y-%m-%d %H:%M:%S"), 
            log.person_count, 
            op_name, 
            image_url
        ])

    return response