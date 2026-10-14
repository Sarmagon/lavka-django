"""Public catalogue queries and prices; archived records never enter the storefront."""
from decimal import Decimal

from django.db.models import (
    Avg, Count, DecimalField, ExpressionWrapper, F, IntegerField, OuterRef,
    Q, Subquery, Sum, Value,
)
from django.db.models.functions import Coalesce, Round
from django.templatetags.static import static
from django.utils import timezone

from orders.models import DeliverySettings, OrderItem
from .models import Discount, Offer, Product, Review


def public_offers():
    return Offer.objects.filter(
        Q(seller__user__isnull=True)
        | Q(seller__user__is_active=True, seller__user__deleted_at__isnull=True)
    )


def products():
    money = DecimalField(max_digits=12, decimal_places=2)
    offers = public_offers().filter(product_id=OuterRef("pk"))
    in_stock = offers.filter(stock__gt=0)
    discounts = Discount.objects.filter(
        product_id=OuterRef("pk"), starts_at__lte=timezone.now(), ends_at__gt=timezone.now()
    ).order_by("-percent", "pk")
    reviews = Review.objects.filter(product_id=OuterRef("pk")).values("product_id")
    purchases = OrderItem.objects.filter(
        offer__product_id=OuterRef("pk"), order__status="paid", order__deleted_at__isnull=True
    ).values("offer__product_id").annotate(total=Sum("quantity"))
    return Product.objects.alive().filter(
        category__deleted_at__isnull=True, category__parent__deleted_at__isnull=True
    ).annotate(
        base_price=Coalesce(
            Subquery(in_stock.order_by("price", "pk").values("price")[:1]),
            Subquery(offers.order_by("price", "pk").values("price")[:1]),
            output_field=money,
        ),
        stock_total=Coalesce(Subquery(offers.values("product_id").annotate(
            total=Sum("stock")).values("total")[:1]), 0),
        discount_percent=Coalesce(Subquery(discounts.values("percent")[:1]), 0),
        discount_start=Subquery(discounts.values("starts_at")[:1]),
        discount_end=Subquery(discounts.values("ends_at")[:1]),
        review_count=Coalesce(Subquery(reviews.annotate(total=Count("pk")).values("total")[:1]), 0),
        rating_value=Coalesce(Subquery(reviews.annotate(total=Avg("rating")).values("total")[:1]), 0.0),
        purchased=Coalesce(Subquery(purchases.values("total")[:1]), Value(0), output_field=IntegerField()),
    ).filter(base_price__isnull=False).annotate(
        current_price=Round(ExpressionWrapper(
            F("base_price") * (Value(Decimal("100")) - F("discount_percent")) / Value(Decimal("100")),
            output_field=money,
        ), 2)
    ).select_related("category", "category__parent").prefetch_related("images")


def delivery_threshold():
    settings = DeliverySettings.objects.order_by("pk").first()
    return settings.free_from if settings else Decimal("2000")


def image_data(product):
    images = [{"src": image.image.url, "alt": image.alt} for image in product.images.all() if image.image]
    if images:
        return images
    from storefront_ui.products import demo_image
    demo = demo_image(product.title) if product.manufacturer == "Лавка · демо" else None
    if demo:
        filename, cell = demo
        return [{"src": static(filename), "alt": product.title, "sheet": True, "cell": cell}]
    return [{"src": static("catalog/placeholder.svg"), "alt": product.title}]


def product_data(product, free_from):
    return {
        "id": product.pk, "title": product.title, "category": product.category_id,
        "manufacturer": product.manufacturer, "price": float(product.current_price),
        "oldPrice": float(product.base_price), "discountPercent": product.discount_percent,
        "count": product.stock_total, "date": product.created_at.isoformat(),
        "description": product.description, "freeDelivery": product.current_price >= free_from,
        "images": image_data(product), "tags": [], "reviews": product.review_count,
        "rating": round(product.rating_value, 2), "purchases": product.purchased,
    }


def specifications(product):
    attributes = product.attributes.select_related("attribute").prefetch_related("options").order_by("attribute_id")
    return [{"name": item.attribute.name, "value": (
        "Да" if item.boolean_value else "Нет"
    ) if item.attribute.kind == "boolean" else item.text_value if item.attribute.kind == "text" else ", ".join(option.value for option in item.options.all())}
        for item in attributes]


def review_data(review):
    return {"id": review.pk, "author": review.author.full_name or review.author.username,
            "text": review.text, "rate": review.rating, "date": review.created_at.isoformat()}
