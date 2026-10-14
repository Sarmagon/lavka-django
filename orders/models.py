from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from core.models import SoftDeleteModel


class Order(SoftDeleteModel):
    class Status(models.TextChoices):
        NEW = "new", "Новый"
        PAYMENT = "payment", "Ожидает оплаты"
        PAID = "paid", "Оплачен"
        FAILED = "failed", "Ошибка оплаты"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=16)
    city = models.CharField(max_length=150)
    address = models.CharField(max_length=500)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW)
    delivery_type = models.CharField(max_length=16, choices=[("ordinary", "Обычная"), ("express", "Экспресс")], default="ordinary")
    delivery_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    payment_type = models.CharField(max_length=16, choices=[("online", "Онлайн картой"), ("someone", "Со случайного счёта")], default="online")
    comment = models.TextField(blank=True, max_length=2000)
    payment_error = models.CharField(max_length=500, blank=True)
    checkout_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(delivery_cost__gte=0), name="order_delivery_nonnegative")]

    def __str__(self):
        return f"Заказ №{self.pk} — {self.full_name} ({self.get_status_display()})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="items")
    offer = models.ForeignKey("catalog.Offer", on_delete=models.PROTECT)
    title = models.CharField(max_length=255)
    seller_name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name="order_item_positive_quantity"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="order_item_nonnegative_price"),
        ]

    def __str__(self):
        return f"{self.title} × {self.quantity} — {self.seller_name}"


class DeliverySettings(models.Model):
    ordinary_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("200"), validators=[MinValueValidator(0)])
    free_from = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("2000"), validators=[MinValueValidator(0)])
    express_extra = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("500"), validators=[MinValueValidator(0)])

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(ordinary_cost__gte=0, free_from__gte=0, express_extra__gte=0), name="delivery_settings_nonnegative")]

    def __str__(self):
        return "Настройки доставки"


class PaymentJob(models.Model):
    """Durable outbox. One job per attempt; a lease permits recovery after a crash."""
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payment_jobs")
    key = models.UUIDField(unique=True, editable=False)
    number = models.CharField(max_length=8)
    state = models.CharField(max_length=16, default="queued", choices=[("queued", "В очереди"), ("running", "Обработка"), ("done", "Завершено")])
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    retries = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["order"], condition=models.Q(state__in=["queued", "running"]), name="one_active_payment_per_order")]
