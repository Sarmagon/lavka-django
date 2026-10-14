from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import login
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, OperationalError, transaction
from django.http import JsonResponse

from accounts.models import User
from catalog.commerce_api import api, ApiError, payload, require_user, _method_not_allowed, _basket_rows, _user_data
from catalog.storefront import image_data
from .models import Order
from .services import delivery_cost, place_order, enqueue_payment


def owned(request, pk):
    user = require_user(request)
    order = Order.objects.alive().filter(user=user, pk=pk).first()
    if not order:
        raise ApiError("Заказ не найден.", 404)
    return order


def order_data(order):
    rows = []
    subtotal = Decimal(0)
    for item in order.items.select_related("offer__product"):
        subtotal += item.unit_price * item.quantity
        rows.append({"id": item.offer.product_id, "title": item.title, "price": float(item.unit_price),
            "count": item.quantity, "seller": item.seller_name, "images": image_data(item.offer.product),
            "description": item.offer.product.description, "shortDescription": item.offer.product.description})
    return {"id": order.pk, "createdAt": order.created_at.isoformat(), "fullName": order.full_name,
        "email": order.email, "phone": order.phone, "city": order.city, "address": order.address,
        "deliveryType": order.delivery_type, "paymentType": order.payment_type,
        "status": order.get_status_display(), "statusCode": order.status,
        "comment": order.comment, "paymentError": order.payment_error or None,
        "deliveryCost": float(order.delivery_cost), "totalCost": float(subtotal + order.delivery_cost), "products": rows}


@api
def checkout(request):
    if request.method != "GET":
        return _method_not_allowed("GET")
    key = request.session.setdefault("checkout_key", str(uuid4()))
    request.session.modified = True
    rows = _basket_rows(request)
    # Decimal prices are recomputed when confirming, this is only a preview.
    subtotal = sum((Decimal(str(row["price"])) * row["count"] for row in rows), Decimal(0))
    user = _user_data(request.user) if request.user.is_authenticated else None
    return JsonResponse({"checkoutKey": key, "products": rows, "user": user,
        "ordinaryCost": float(delivery_cost(subtotal, "ordinary")), "expressCost": float(delivery_cost(subtotal, "express"))})


@api
def register_checkout(request):
    if request.method != "POST":
        return _method_not_allowed("POST")
    data = payload(request)
    email, name, password = data.get("email"), data.get("fullName"), data.get("password")
    if not isinstance(email, str) or len(email) > 254:
        raise ApiError("Укажите email.", field="email")
    email = email.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        raise ApiError("Укажите корректный email.", field="email")
    if User.objects.filter(email__iexact=email).exists():
        raise ApiError("Пользователь с указанным email существует, вы можете авторизоваться", field="email")
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        raise ApiError("Укажите ФИО.", field="fullName")
    if not isinstance(password, str) or not password or password != data.get("passwordReply"):
        raise ApiError("Пароли не совпадают.", field="passwordReply")
    user = User(username="customer-" + uuid4().hex, email=email, full_name=name.strip(), phone=data.get("phone") or None)
    try:
        validate_password(password, user)
        with transaction.atomic():
            user.set_password(password)
            user.save()
            group = Group.objects.filter(name="Покупатели").first()
            if group:
                user.groups.add(group)
    except ValidationError as error:
        errors = error.message_dict if hasattr(error, "message_dict") else {"password": error.messages}
        return JsonResponse({"errors": {k: " ".join(v) for k, v in errors.items()}}, status=400)
    except IntegrityError:
        raise ApiError("Email или телефон уже используется.", 409)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return JsonResponse({"user": _user_data(user)}, status=201)


@api
def orders(request):
    user = require_user(request)
    if request.method == "GET":
        return JsonResponse([order_data(o) for o in Order.objects.alive().filter(user=user).order_by("-created_at", "-pk")], safe=False)
    if request.method != "POST":
        return _method_not_allowed("GET, POST")
    try:
        order = place_order(request, user, payload(request))
    except (IntegrityError, OperationalError):
        raise ApiError("Заказ уже оформляется. Обновите страницу.", 409)
    return JsonResponse({"orderId": order.pk, "paymentType": order.payment_type}, status=201)


@api
def detail(request, pk):
    if request.method != "GET":
        return _method_not_allowed("GET")
    return JsonResponse(order_data(owned(request, pk)))


@api
def payment(request, pk):
    order = owned(request, pk)
    if request.method == "GET":
        return JsonResponse(order_data(order))
    if request.method != "POST":
        return _method_not_allowed("GET, POST")
    try:
        job = enqueue_payment(order, payload(request))
    except (IntegrityError, OperationalError):
        raise ApiError("Оплата уже обрабатывается. Обновите страницу.", 409)
    return JsonResponse({"jobId": job.pk, "orderId": order.pk, "status": "payment"}, status=202)


@api
def account(request):
    user = require_user(request)
    last = Order.objects.alive().filter(user=user).order_by("-created_at", "-pk").first()
    return JsonResponse({**_user_data(user), "avatar": {"src": user.avatar.url, "alt": user.full_name} if user.avatar else None,
        "orders": [order_data(last)] if last else []})
