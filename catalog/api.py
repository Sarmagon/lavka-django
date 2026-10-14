"""JSON endpoints matching the supplied frontend; no additional framework required."""
import json
import re
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.core.paginator import Paginator
from django.http import JsonResponse
from django.db.models import Q
from django.templatetags.static import static

from .models import Attribute, AttributeOption, Category, ProductAttribute, Review
from .storefront import (
    delivery_threshold, product_data, products, public_offers, review_data, specifications,
)


class InputError(Exception):
    def __init__(self, field, message, status=400):
        self.field, self.message, self.status = field, message, status


def endpoint(methods=("GET",)):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                response = JsonResponse({"errors": {"__all__": "Метод не поддерживается."}}, status=405)
                response["Allow"] = ", ".join(methods)
                return response
            try:
                return JsonResponse(view(request, *args, **kwargs), safe=False)
            except InputError as error:
                return JsonResponse({"errors": {error.field: error.message}}, status=error.status)
        return wrapped
    return decorate


def integer(value, field, minimum=1, maximum=2147483647):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,10}", str(value)):
        raise InputError(field, "Введите целое число.")
    number = int(value)
    if not minimum <= number <= maximum:
        raise InputError(field, f"Допустимое значение: от {minimum} до {maximum}.")
    return number


def boolean(value, field):
    if str(value).lower() not in ("true", "false", "1", "0"):
        raise InputError(field, "Ожидается true или false.")
    return str(value).lower() in ("true", "1")


def price(value, field):
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise InputError(field, "Введите корректную цену.")
    if not result.is_finite() or not 0 <= result <= Decimal("9999999999.99") or result.as_tuple().exponent < -2:
        raise InputError(field, "Цена должна быть неотрицательной, максимум два знака после запятой.")
    return result


def category_ids(request):
    value = request.GET.get("category")
    if value in (None, ""):
        return None
    pk = integer(value, "category")
    category = Category.objects.alive().filter(pk=pk, parent__deleted_at__isnull=True).first()
    if category is None:
        raise InputError("category", "Категория не найдена.", 404)
    return [pk, *category.children.alive().values_list("pk", flat=True)]


def paginate(queryset, request, serialize, default=20, maximum=100):
    page_number = integer(request.GET.get("currentPage", "1"), "currentPage")
    limit = integer(request.GET.get("limit", str(default)), "limit", maximum=maximum)
    paginator = Paginator(queryset, limit)
    if page_number > paginator.num_pages:
        raise InputError("currentPage", "Страница не найдена.", 404)
    page = paginator.page(page_number)
    return {"items": [serialize(item) for item in page], "currentPage": page.number,
            "lastPage": paginator.num_pages, "total": paginator.count}


def find_product(pk):
    pk = integer(pk, "product")
    product = products().filter(pk=pk).first()
    if product is None:
        raise InputError("__all__", "Товар не найден.", 404)
    return product


@endpoint()
def categories(request):
    all_categories = list(Category.objects.alive().filter(parent__deleted_at__isnull=True).order_by("name", "pk"))
    def serialize(category):
        return {"id": category.pk, "title": category.name,
                "image": {"src": static("catalog/category.svg"), "alt": category.name},
                "subcategories": []}
    roots = {category.pk: serialize(category) for category in all_categories if category.parent_id is None}
    for category in all_categories:
        if category.parent_id in roots:
            roots[category.parent_id]["subcategories"].append(serialize(category))
    return list(roots.values())


@endpoint()
def filters(request):
    ids = category_ids(request)
    queryset = products()
    if ids:
        queryset = queryset.filter(category_id__in=ids)
    attributes = Attribute.objects.filter(category__deleted_at__isnull=True, category__parent__deleted_at__isnull=True)
    if ids:
        parent = Category.objects.get(pk=ids[0]).parent_id
        attributes = attributes.filter(category_id__in=[*ids, *([parent] if parent else [])])
    return {
        "manufacturers": list(queryset.order_by("manufacturer").values_list("manufacturer", flat=True).distinct()),
        "attributes": [{"id": item.pk, "name": item.name, "kind": item.kind,
                        "options": [{"id": option.pk, "value": option.value} for option in item.options.all()]}
                       for item in attributes.order_by("name", "pk").prefetch_related("options")],
    }


@endpoint()
def catalog(request):
    ids = category_ids(request)
    queryset = products()
    if ids:
        queryset = queryset.filter(category_id__in=ids)
    def value(name, default=None):
        return request.GET.get(f"filter[{name}]", request.GET.get(name, default))
    name = value("name", "").strip()
    if len(name) > 200:
        raise InputError("name", "Не более 200 символов.")
    if name:
        # SQLite's icontains is ASCII-only; iregex also handles Cyrillic.
        pattern = re.escape(name)
        queryset = queryset.filter(title__iregex=pattern)
    lower, upper = value("minPrice"), value("maxPrice")
    lower = price(lower, "minPrice") if lower not in (None, "") else None
    upper = price(upper, "maxPrice") if upper not in (None, "") else None
    if lower is not None and upper is not None and lower > upper:
        raise InputError("maxPrice", "Максимальная цена меньше минимальной.")
    if lower is not None:
        queryset = queryset.filter(current_price__gte=lower)
    if upper is not None:
        queryset = queryset.filter(current_price__lte=upper)
    if boolean(value("available", "true"), "available"):
        queryset = queryset.filter(stock_total__gt=0)
    threshold = delivery_threshold()
    if boolean(value("freeDelivery", "false"), "freeDelivery"):
        queryset = queryset.filter(current_price__gte=threshold)
    manufacturer = value("manufacturer", "")
    if manufacturer:
        queryset = queryset.filter(manufacturer=manufacturer)
    for key in request.GET:
        match = re.fullmatch(r"attributes\[([0-9]+)\](?:\[\])?", key)
        if not match:
            if key.startswith("attributes"):
                raise InputError("attributes", "Неверный формат характеристики.")
            continue
        attribute_id = integer(match[1], "attributes")
        attribute = Attribute.objects.filter(pk=attribute_id, category__deleted_at__isnull=True,
                                             category__parent__deleted_at__isnull=True).first()
        if attribute is None:
            raise InputError("attributes", "Характеристика не найдена.")
        values = request.GET.getlist(key)
        records = ProductAttribute.objects.filter(attribute=attribute)
        if attribute.kind == "boolean":
            if len(values) != 1:
                raise InputError("attributes", "Выберите одно логическое значение.")
            records = records.filter(boolean_value=boolean(values[0], "attributes"))
        elif attribute.kind == "text":
            if len(values) != 1 or len(values[0]) > 500:
                raise InputError("attributes", "Введите текст до 500 символов.")
            records = records.filter(text_value__iregex=re.escape(values[0]))
        else:
            choices = {integer(item, "attributes") for item in values}
            if attribute.kind == "single" and len(choices) != 1:
                raise InputError("attributes", "Для этой характеристики выберите одно значение.")
            if attribute.options.filter(pk__in=choices).count() != len(choices):
                raise InputError("attributes", "Значение не относится к характеристике.")
            records = records.filter(options__pk__in=choices)
        queryset = queryset.filter(pk__in=records.values("product_id"))
    tags = request.GET.getlist("tags[]") or request.GET.getlist("tags")
    if tags:
        choices = {integer(item, "tags") for item in tags}
        if AttributeOption.objects.filter(pk__in=choices).count() != len(choices):
            raise InputError("tags", "Тег не найден.")
        queryset = queryset.filter(attributes__options__pk__in=choices).distinct()
    sorting = {"rating": "purchased", "price": "current_price", "reviews": "review_count", "date": "created_at"}
    sort = request.GET.get("sort") or "date"
    direction = request.GET.get("sortType") or "dec"
    if sort not in sorting or direction not in ("inc", "dec"):
        raise InputError("sort", "Неизвестный порядок сортировки.")
    queryset = queryset.order_by(("-" if direction == "dec" else "") + sorting[sort], "pk")
    return paginate(queryset, request, lambda item: product_data(item, threshold))


@endpoint()
def popular(request):
    threshold = delivery_threshold()
    return [product_data(item, threshold) for item in products().filter(stock_total__gt=0).order_by("sort_index", "-purchased", "pk")[:8]]


@endpoint()
def limited(request):
    threshold = delivery_threshold()
    return [product_data(item, threshold) for item in products().filter(limited=True, stock_total__gt=0).order_by("sort_index", "-created_at", "pk")[:16]]


@endpoint()
def banners(request):
    threshold = delivery_threshold()
    return [product_data(item, threshold) for item in products().filter(stock_total__gt=0).order_by("sort_index", "pk")[:3]]


@endpoint()
def sales(request):
    threshold = delivery_threshold()
    def serialize(item):
        return {**product_data(item, threshold), "price": float(item.base_price),
                "salePrice": float(item.current_price), "dateFrom": item.discount_start.date().isoformat(),
                "dateTo": item.discount_end.date().isoformat()}
    return paginate(products().filter(discount_percent__gt=0, stock_total__gt=0).order_by("-discount_percent", "pk"), request, serialize)


@endpoint()
def tags(request):
    ids = category_ids(request)
    queryset = products()
    if ids:
        queryset = queryset.filter(category_id__in=ids)
    options = AttributeOption.objects.filter(productattribute__product_id__in=queryset.values("pk")).distinct().order_by("pk")[:20]
    return [{"id": item.pk, "name": item.value} for item in options]


@endpoint()
def detail(request, pk):
    product = find_product(pk)
    reviews = product.reviews.select_related("author").order_by("-created_at", "-pk")
    return {**product_data(product, delivery_threshold()), "fullDescription": product.description,
            "specifications": specifications(product), "reviewCount": product.review_count,
            "reviews": [review_data(review) for review in reviews[:5]],
            "reviewsLastPage": max(1, (product.review_count + 4) // 5),
            "canReview": request.user.is_authenticated and request.user.is_active and not request.user.deleted_at,
            "offers": [{"id": offer.pk, "seller": offer.seller.name, "price": float(offer.price), "stock": offer.stock}
                       for offer in public_offers().filter(product=product).select_related("seller").order_by("price", "pk")]}


@endpoint(("GET", "POST"))
def reviews(request, pk):
    product = find_product(pk)
    if request.method == "POST":
        if not request.user.is_authenticated or not request.user.is_active or request.user.deleted_at:
            raise InputError("__all__", "Войдите в аккаунт, чтобы оставить отзыв.", 403)
        if request.content_type != "application/json":
            raise InputError("__all__", "Ожидается JSON.", 415)
        try:
            payload = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            raise InputError("__all__", "Некорректный JSON.")
        if not isinstance(payload, dict):
            raise InputError("__all__", "Ожидается объект JSON.")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 5000:
            raise InputError("text", "Введите отзыв от 1 до 5000 символов.")
        rating = integer(payload.get("rate"), "rate", maximum=5)
        Review.objects.create(product=product, author=request.user, text=text.strip(), rating=rating)
    queryset = product.reviews.select_related("author").order_by("-created_at", "-pk")
    return paginate(queryset, request, review_data, default=5, maximum=50)
