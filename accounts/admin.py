from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User
from core.admin import SoftDeleteAdmin


@admin.register(User)
class AccountAdmin(SoftDeleteAdmin, UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Профиль", {"fields": ("full_name", "phone", "avatar", "deleted_at")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Профиль", {"fields": ("full_name", "email", "phone")}),)
    readonly_fields = ("deleted_at",)

    def delete_model(self, request, obj):
        obj.delete()

    def delete_queryset(self, request, queryset):
        queryset.delete()
