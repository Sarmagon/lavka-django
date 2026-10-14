"""Authentication, customer profile and session-backed basket endpoints."""
import json
import re

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse

from accounts.models import User
from core.validators import validate_image
from .storefront import delivery_threshold, product_data, products, public_offers


class ApiError(Exception):
    def __init__(self, message, status=400, field="__all__"):
        self.message, self.status, self.field = message, status, field


def api(view):
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ApiError as error:
            return JsonResponse({"errors": {error.field: error.message}}, status=error.status)
        except (TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"errors": {"__all__": "Некорректные данные."}}, status=400)
    wrapped.__name__ = view.__name__
    return wrapped


def payload(request):
    if request.content_type != "application/json":
        raise ApiError("Ожидается JSON.", 415)
    try:
        value = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ApiError("Некорректный JSON.")
    if not isinstance(value, dict):
        raise ApiError("Ожидается объект JSON.")
    return value


def require_user(request):
    user = request.user
    if not user.is_authenticated or not user.is_active or user.deleted_at:
        raise ApiError("Войдите в аккаунт.", 401)
    return user


def _user_data(user):
    return {"id": user.pk, "username": user.username, "fullName": user.full_name,
            "email": user.email, "phone": user.phone or ""}


def _method_not_allowed(allow):
    response = JsonResponse({"errors": {"__all__": "Метод не поддерживается."}}, status=405)
    response["Allow"] = allow
    return response


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError
    if isinstance(value, str) and not value.isdecimal():
        raise ValueError
    return int(value)


@api
def sign_in(request):
    if request.method != "POST":
        return _method_not_allowed("POST")
    data = payload(request)
    username, password = data.get("username"), data.get("password")
    if not isinstance(username, str) or not username.strip():
        raise ApiError("Укажите логин.", field="username")
    if not isinstance(password, str) or not password:
        raise ApiError("Укажите пароль.", field="password")
    user = authenticate(request, username=username.strip(), password=password)
    if user is None:
        account = User.objects.filter(email__iexact=username.strip()).first()
        if account:
            user = authenticate(request, username=account.username, password=password)
    if user is None or not user.is_active or user.deleted_at:
        raise ApiError("Неверный логин или пароль.", 401)
    login(request, user)
    return JsonResponse({"user": _user_data(user)})


@api
def sign_up(request):
    if request.method != "POST":
        return _method_not_allowed("POST")
    data = payload(request)
    username, full_name = data.get("username"), data.get("name", data.get("fullName"))
    email, password = data.get("email"), data.get("password")
    if not isinstance(username, str) or not username.strip() or len(username.strip()) > 150:
        raise ApiError("Укажите логин длиной до 150 символов.", field="username")
    if not isinstance(full_name, str) or not full_name.strip() or len(full_name.strip()) > 255:
        raise ApiError("Укажите имя длиной до 255 символов.", field="name")
    if not isinstance(email, str) or not email.strip() or len(email.strip()) > 254:
        raise ApiError("Укажите email.", field="email")
    email = email.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        raise ApiError("Укажите корректный email.", field="email")
    if not isinstance(password, str):
        raise ApiError("Укажите пароль.", field="password")
    username = username.strip()
    if User.objects.filter(username__iexact=username).exists():
        raise ApiError("Этот логин уже занят.", field="username")
    if User.objects.filter(email__iexact=email).exists():
        raise ApiError("Этот email уже зарегистрирован.", field="email")
    user = User(username=username, full_name=full_name.strip(), email=email)
    try:
        validate_password(password, user=user)
    except ValidationError as error:
        raise ApiError(" ".join(error.messages), field="password")
    try:
        user.set_password(password)
        user.save()
    except ValidationError as error:
        field, messages = next(iter(error.message_dict.items())) if hasattr(error, "message_dict") else ("__all__", error.messages)
        raise ApiError(" ".join(messages), field=field)
    buyer_group = Group.objects.filter(name="Покупатели").first()
    if buyer_group:
        user.groups.add(buyer_group)
    login(request, user)
    return JsonResponse({"user": _user_data(user)}, status=201)


@api
def sign_out(request):
    if request.method != "POST":
        return _method_not_allowed("POST")
    basket_items = _basket(request)
    logout(request)
    if basket_items:
        request.session["basket"] = basket_items
    return JsonResponse({"success": True})


@api
def profile(request):
    user = require_user(request)
    if request.method == "GET":
        avatar = {"src": user.avatar.url, "alt": user.full_name} if user.avatar else None
        return JsonResponse({**_user_data(user), "avatar": avatar})
    if request.method != "POST":
        return _method_not_allowed("GET, POST")
    data = payload(request)
    full_name, email, phone = data.get("fullName"), data.get("email"), data.get("phone", "")
    if not isinstance(full_name, str) or not full_name.strip() or len(full_name.strip()) > 255:
        raise ApiError("Укажите имя длиной до 255 символов.", field="fullName")
    if not isinstance(email, str) or not email.strip() or len(email.strip()) > 254:
        raise ApiError("Укажите email.", field="email")
    email = email.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        raise ApiError("Укажите корректный email.", field="email")
    if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        raise ApiError("Этот email уже используется.", field="email")
    if not isinstance(phone, str):
        raise ApiError("Укажите телефон строкой.", field="phone")
    normalized_phone = re.sub(r"[\s()\-]", "", phone.strip())
    if normalized_phone and not re.fullmatch(r"\+[1-9][0-9]{6,14}", normalized_phone):
        raise ApiError("Используйте международный формат: +79991234567.", field="phone")
    if normalized_phone and User.objects.filter(phone=normalized_phone).exclude(pk=user.pk).exists():
        raise ApiError("Этот телефон уже используется.", field="phone")
    user.full_name, user.email, user.phone = full_name.strip(), email, normalized_phone or None
    try:
        user.save()
    except ValidationError as error:
        field, messages = next(iter(error.message_dict.items())) if hasattr(error, "message_dict") else ("__all__", error.messages)
        raise ApiError(" ".join(messages), field=field)
    avatar = {"src": user.avatar.url, "alt": user.full_name} if user.avatar else None
    return JsonResponse({**_user_data(user), "avatar": avatar})


@api
def profile_password(request):
    user = require_user(request)
    if request.method != "POST":
        return _method_not_allowed("POST")
    data = payload(request)
    current, new = data.get("currentPassword"), data.get("newPassword")
    if not isinstance(current, str) or not current or not user.check_password(current):
        raise ApiError("Текущий пароль указан неверно.", 400, "currentPassword")
    if not isinstance(new, str) or not new:
        raise ApiError("Укажите новый пароль.", field="newPassword")
    try:
        validate_password(new, user=user)
    except ValidationError as error:
        raise ApiError(" ".join(error.messages), field="newPassword")
    user.set_password(new)
    user.save(update_fields=["password"])
    update_session_auth_hash(request, user)
    return JsonResponse({"success": True})


@api
def profile_avatar(request):
    user = require_user(request)
    if request.method == "DELETE":
        if user.avatar:
            user.avatar.delete(save=False)
            user.avatar = ""
            user.save(update_fields=["avatar"])
        return JsonResponse({"avatar": None})
    if request.method != "POST":
        return _method_not_allowed("POST, DELETE")
    upload = request.FILES.get("avatar")
    if upload is None:
        raise ApiError("Выберите изображение.", field="avatar")
    try:
        validate_image(upload)
    except ValidationError as error:
        raise ApiError(" ".join(error.messages), field="avatar")
    old_avatar = user.avatar.name if user.avatar else None
    user.avatar = upload
    try:
        user.save()
    except ValidationError as error:
        field, messages = next(iter(error.message_dict.items())) if hasattr(error, "message_dict") else ("avatar", error.messages)
        raise ApiError(" ".join(messages), field=field)
    if old_avatar and old_avatar != user.avatar.name:
        user.avatar.storage.delete(old_avatar)
    return JsonResponse({"avatar": {"src": user.avatar.url, "alt": user.full_name}})


def _basket(request):
    value = request.session.get("basket", {})
    return value if isinstance(value, dict) else {}


def _basket_rows(request):
    threshold, rows = delivery_threshold(), []
    for raw_id, raw_count in _basket(request).items():
        try:
            product_id, count = int(raw_id), int(raw_count)
        except (ValueError, TypeError):
            continue
        product = products().filter(pk=product_id).first()
        offer = public_offers().filter(product_id=product_id, stock__gt=0).order_by("price", "pk").first()
        if product is None or offer is None or count < 1:
            continue
        item = product_data(product, threshold)
        item["price"] = float(product.current_price)
        item["count"] = min(count, offer.stock)
        item["offerId"] = offer.pk
        rows.append(item)
    return rows


@api
def basket(request):
    if request.method == "GET":
        return JsonResponse(_basket_rows(request), safe=False)
    if request.method not in ("POST", "DELETE"):
        return _method_not_allowed("GET, POST, DELETE")
    data = payload(request)
    try:
        product_id, count = _integer(data.get("id")), _integer(data.get("count", 1))
    except (TypeError, ValueError):
        raise ApiError("Укажите товар и количество.")
    if product_id < 1:
        raise ApiError("Укажите корректный товар.", field="id")
    if not 1 <= count <= 999:
        raise ApiError("Количество должно быть от 1 до 999.", field="count")
    product = products().filter(pk=product_id).first()
    if product is None:
        raise ApiError("Товар не найден.", 404, "id")
    offer = public_offers().filter(product=product, stock__gt=0).order_by("price", "pk").first()
    if offer is None:
        raise ApiError("Товара нет в наличии.", 409, "id")
    items = dict(_basket(request))
    try:
        current = max(0, _integer(items.get(str(product_id), 0)))
    except (TypeError, ValueError):
        current = 0
    if request.method == "POST":
        if current + count > offer.stock:
            raise ApiError(f"Доступно только {offer.stock} шт.", 409, "count")
        items[str(product_id)] = current + count
    else:
        remaining = current - count
        if remaining > 0:
            items[str(product_id)] = remaining
        else:
            items.pop(str(product_id), None)
    request.session["basket"] = items
    request.session.modified = True
    return JsonResponse(_basket_rows(request), safe=False)
