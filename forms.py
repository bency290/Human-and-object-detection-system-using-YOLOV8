from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
import re


class RegisterForm(forms.Form):
    full_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'placeholder': 'Full Name'})
    )

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'placeholder': 'Email Address'})
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Password'})
    )

    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm Password'})
    )

    agree_terms = forms.BooleanField(
        error_messages={'required': 'You must agree to the Terms and Policy'}
    )


class VideoUploadForm(forms.Form):
    video = forms.FileField()

    # ----------------------------
    # VALIDATIONS
    # ----------------------------

    def clean_full_name(self):
        full_name = self.cleaned_data.get('full_name')
        if len(full_name.split()) < 2:
            raise ValidationError("Enter first and last name")
        return full_name

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("Email already registered")
        return email

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if len(password) < 6:
            raise ValidationError("Password must be at least 6 characters long")
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', "Passwords do not match")
