from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', views.login_user, name='login_user'),
    path('logout/', views.logout_user, name='logout'),
    path('dashboard-redirect/', views.dashboard_redirect, name='dashboard_redirect'),
    path('admin-panel/', views.admin_panel, name='admin_panel'),
    path('admin-panel/toggle-user/<int:user_id>/', views.toggle_user_status, name='toggle_user'),
    # Pages
    path('dashboard/', views.dashboard, name='dashboard'),
    path('profile/', views.profile, name='profile'),
    path('reset-password/', views.reset_password, name='reset_password'),
    # YOLO
    path('video_feed/', views.video_feed, name='video_feed'),
    path('api/chat/stream/', views.chat_stream, name='chat_stream'),
    path("upload-detect/", views.upload_detect, name="upload_detect"),
    path("test-email/", views.test_email, name="test_email"),
    path('history/<int:detection_id>/download-json/', views.download_detection_json, name='download_json'),
    path('admin-panel/export-logs/', views.export_detection_logs, name='export_logs'),
    # 1. Page where user enters their email
    path('reset_password/', 
         auth_views.PasswordResetView.as_view(template_name='authenticate/password_reset.html'), 
         name='password_reset'),
    # 2. Page showing "Email has been sent" message
    path('reset_password_sent/', 
         auth_views.PasswordResetDoneView.as_view(template_name='authenticate/password_reset_sent.html'), 
         name='password_reset_done'),
    # 3. The link embedded in the email (contains unique uidb64 and token)
    path('reset/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(template_name='authenticate/password_reset_form.html'), 
         name='password_reset_confirm'),

    # 4. Page showing "Password successfully changed" message
    path('reset_password_complete/', 
         auth_views.PasswordResetCompleteView.as_view(template_name='authenticate/password_reset_done.html'), 
         name='password_reset_complete'),
]