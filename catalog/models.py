from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

from core.models import SoftDeleteModel
from core.validators import validate_image


class Category(SoftDeleteModel):
    name = models.CharField(max_length=150)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")

    def clean(self):
        if self.parent_id:
            if self.parent_id == self.pk or self.parent.parent_id:
                raise ValidationError({"parent": "Допускаются только два уровня категорий."})
            if self.pk and self.children.exists():
                raise ValidationError({"parent": "Категорию с подкатегориями нельзя переместить на второй уровень."})
            if self.parent.deleted_at:
                raise ValidationError({"parent": "Родительская категория удалена."})

    def __str__(self):
        return self.name


class Seller(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Attribute(models.Model):
    class Kind(models.TextChoices):
        SINGLE = "single", "Одиночный выбор"
        MULTIPLE = "multiple", "Множественный выбор"
        BOOLEAN = "boolean", "Галочка"
        TEXT = "text", "Текст"

    name = models.CharField(max_length=150)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=Kind.choices)

    def __str__(self):
        return self.name


class AttributeOption(models.Model):
    attribute = models.ForeignKey(Attribute, on_delete=models.PROTECT, related_name="options")
    value = models.CharField(max_length=150)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["attribute", "value"], name="unique_attribute_option")]

    def __str__(self):
        return self.value


class Product(SoftDeleteModel):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    manufacturer = models.CharField(max_length=150)
    sort_index = models.PositiveIntegerField(default=0)
    limited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.category_id and self.category.deleted_at:
            raise ValidationError({"category": "Категория удалена."})

    def __str__(self):
        return self.title


class Offer(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="offers")
    seller = models.ForeignKey(Seller, on_delete=models.PROTECT)
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    stock = models.PositiveIntegerField(default=0)

    def clean(self):
        if self.product_id and self.product.deleted_at:
            raise ValidationError({"product": "Товар удалён."})

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "seller"], name="unique_product_seller"),
            models.CheckConstraint(condition=models.Q(price__gt=0), name="offer_positive_price"),
        ]

    def __str__(self):
        return f"{self.product} — {self.seller}: {self.price}"


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="images")
    image = models.ImageField(upload_to="products/", validators=[validate_image])
    alt = models.CharField(max_length=255)
    sort_index = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_index", "pk")

    def __str__(self):
        return f"{self.product} — {self.alt}"


class ProductAttribute(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="attributes")
    attribute = models.ForeignKey(Attribute, on_delete=models.PROTECT)
    options = models.ManyToManyField(AttributeOption, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)
    text_value = models.CharField(max_length=500, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "attribute"], name="unique_product_attribute")]

    def clean(self):
        if self.product_id and self.attribute_id:
            if self.attribute.category_id not in (self.product.category_id, self.product.category.parent_id):
                raise ValidationError({"attribute": "Характеристика не относится к категории товара."})
            if self.attribute.kind == Attribute.Kind.BOOLEAN and self.boolean_value is None:
                raise ValidationError({"boolean_value": "Выберите да или нет."})
            if self.attribute.kind != Attribute.Kind.BOOLEAN and self.boolean_value is not None:
                raise ValidationError({"boolean_value": "Это поле только для галочки."})
            if self.attribute.kind == Attribute.Kind.TEXT and not self.text_value.strip():
                raise ValidationError({"text_value": "Укажите текст характеристики."})
            if self.attribute.kind != Attribute.Kind.TEXT and self.text_value:
                raise ValidationError({"text_value": "Это поле только для текстовой характеристики."})

    def __str__(self):
        return f"{self.product} — {self.attribute}"


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="reviews")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    text = models.TextField()
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name="review_rating_range")]

    def __str__(self):
        return f"{self.product} — {self.author}: {self.rating}/5"


class Discount(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="discounts")
    percent = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(100)])
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(percent__gte=1, percent__lte=100), name="discount_percent_range"),
            models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")), name="discount_valid_period"),
        ]

    def clean(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "Окончание должно быть позже начала."})

    def __str__(self):
        return f"{self.product} — скидка {self.percent}%"
