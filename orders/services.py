import re
from decimal import Decimal
from uuid import UUID, uuid4

from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from catalog.commerce_api import ApiError, _basket, _integer
from catalog.storefront import products, public_offers
from .models import DeliverySettings, Order, OrderItem, PaymentJob


def delivery_cost(subtotal, kind):
    cfg = DeliverySettings.objects.order_by("pk").first() or DeliverySettings()
    ordinary = Decimal(0) if subtotal >= cfg.free_from else cfg.ordinary_cost
    return ordinary + (cfg.express_extra if kind == "express" else Decimal(0))


def fields(data):
    result = {}
    for name, limit in [("fullName", 255), ("email", 254), ("phone", 16), ("city", 150), ("address", 500)]:
        value = data.get(name)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise ApiError("Заполните поле корректно.", field=name)
        result[name] = value.strip()
    try:
        validate_email(result["email"])
    except ValidationError:
        raise ApiError("Укажите корректный email.", field="email")
    if not re.fullmatch(r"\+[1-9][0-9]{6,14}", result["phone"]):
        raise ApiError("Используйте международный формат: +79991234567.", field="phone")
    for name, allowed in [("deliveryType", ("ordinary", "express")), ("paymentType", ("online", "someone"))]:
        if data.get(name) not in allowed:
            raise ApiError("Выберите один из вариантов.", field=name)
        result[name] = data[name]
    comment = data.get("comment", "")
    if not isinstance(comment, str) or len(comment) > 2000:
        raise ApiError("Комментарий не длиннее 2000 символов.", field="comment")
    result["comment"] = comment.strip()
    return result


def checkout_rows(request):
    rows = []
    for raw_id, raw_count in sorted(_basket(request).items()):
        try:
            pk, count = _integer(raw_id), _integer(raw_count)
        except ValueError:
            raise ApiError("Проверьте корзину.", 409)
        product = products().filter(pk=pk).first()
        offer = public_offers().select_for_update().filter(product_id=pk, stock__gt=0).order_by("price", "pk").first()
        if product is None or offer is None or not 1 <= count <= 999 or offer.stock < count:
            raise ApiError("Изменились остатки. Проверьте корзину.", 409)
        # Apply the same active discount to the selected seller's price.
        price = (offer.price * (Decimal(100) - product.discount_percent) / Decimal(100)).quantize(Decimal("0.01"))
        rows.append((product, offer, count, price))
    if not rows:
        raise ApiError("Корзина пуста.", 409)
    return rows


@transaction.atomic
def place_order(request, user, data):
    try:
        key = UUID(str(data.get("checkoutKey")))
    except (ValueError, TypeError):
        raise ApiError("Обновите страницу оформления заказа.", field="checkoutKey")
    existing = Order.objects.filter(checkout_key=key).first()
    if existing:
        if existing.user_id != user.pk or existing.deleted_at:
            raise ApiError("Заказ не найден.", 404)
        return existing
    if str(key) != request.session.get("checkout_key"):
        raise ApiError("Обновите страницу оформления заказа.", 409)
    info, rows = fields(data), checkout_rows(request)
    subtotal = sum((price * count for _, _, count, price in rows), Decimal(0))
    order = Order.objects.create(user=user, full_name=info["fullName"], email=info["email"], phone=info["phone"],
        city=info["city"], address=info["address"], delivery_type=info["deliveryType"],
        payment_type=info["paymentType"], comment=info["comment"], checkout_key=key,
        delivery_cost=delivery_cost(subtotal, info["deliveryType"]), confirmed_at=timezone.now())
    for product, offer, count, price in rows:
        # Reserve stock once at confirmation, never on payment retry.
        changed = type(offer).objects.filter(pk=offer.pk, stock__gte=count).update(stock=F("stock") - count)
        if changed != 1:
            raise ApiError("Остатки изменились. Повторите оформление.", 409)
        OrderItem.objects.create(order=order, offer=offer, title=product.title,
            seller_name=offer.seller.name, unit_price=price, quantity=count)
    request.session["basket"] = {}
    request.session.pop("checkout_key", None)
    return order


@transaction.atomic
def enqueue_payment(order, data):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status == Order.Status.PAID:
        raise ApiError("Заказ уже оплачен.", 409)
    active = order.payment_jobs.exclude(state="done").first()
    if active:
        return active
    kind = data.get("paymentType", order.payment_type)
    if kind not in ("online", "someone"):
        raise ApiError("Выберите способ оплаты.", field="paymentType")
    number = data.get("number")
    if not isinstance(number, str) or not re.fullmatch(r"[0-9]{1,8}", number) or int(number) % 2:
        raise ApiError("Введите чётный номер из 1–8 цифр.", field="number")
    job = PaymentJob.objects.create(order=order, key=uuid4(), number=number)
    order.status, order.payment_type, order.payment_error = Order.Status.PAYMENT, kind, ""
    order.save(update_fields=["status", "payment_type", "payment_error"])
    return job
