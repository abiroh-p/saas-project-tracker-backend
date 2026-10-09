from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Project Tracker", {"fields": ("full_name", "role")}),
    )
    list_display = UserAdmin.list_display + ("full_name",)
    search_fields = UserAdmin.search_fields + ("full_name",)
