from django.contrib import admin
from core.admin import SoftDeleteAdmin
from .models import Order, OrderItem, DeliverySettings


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("offer", "title", "seller_name", "unit_price", "quantity")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(SoftDeleteAdmin):
    list_display = ("id", "user", "status", "created_at", "deleted_at")
    list_filter = ("status", "deleted_at")
    inlines = (OrderItemInline,)
    readonly_fields = ("user", "status", "delivery_cost", "created_at", "confirmed_at", "checkout_key", "payment_error", "deleted_at")

    def has_add_permission(self, request):
        return False


@admin.register(DeliverySettings)
class DeliverySettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not DeliverySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
