from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    # Add your custom fields to the fieldsets so they show up in the admin panel
    fieldsets = UserAdmin.fieldsets + (
        ('System Roles', {'fields': ('is_system_admin', 'is_standard_user')}),
    )
    list_display = ['username', 'email', 'is_system_admin', 'is_standard_user', 'is_staff']

admin.site.register(CustomUser, CustomUserAdmin)