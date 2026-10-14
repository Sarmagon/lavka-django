import json
from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from orders.models import DeliverySettings, Order, OrderItem
from .models import Attribute, AttributeOption, Category, Discount, Offer, Product, ProductAttribute, Review, Seller


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class StorefrontTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Category.objects.create(name="Техника")
        cls.category = Category.objects.create(name="Телефоны", parent=cls.root)
        cls.other = Category.objects.create(name="Книги")
        cls.user = User.objects.create_user(username="reader", email="reader@example.com", full_name="Читатель", password="test12345")
        cls.seller = Seller.objects.create(name="Первый магазин")
        cls.product = Product.objects.create(title="Телефон Синий", category=cls.category, manufacturer="Марка А", limited=True)
        cls.offer = Offer.objects.create(product=cls.product, seller=cls.seller, price="2500.00", stock=4)
        cls.second = Product.objects.create(title="Книга", category=cls.other, manufacturer="Издатель")
        Offer.objects.create(product=cls.second, seller=cls.seller, price="100.00", stock=0)
        cls.single = Attribute.objects.create(name="Цвет", category=cls.root, kind="single")
        cls.blue = AttributeOption.objects.create(attribute=cls.single, value="Синий")
        cls.red = AttributeOption.objects.create(attribute=cls.single, value="Красный")
        pa = ProductAttribute.objects.create(product=cls.product, attribute=cls.single)
        pa.options.add(cls.blue)
        cls.multi = Attribute.objects.create(name="Связь", category=cls.category, kind="multiple")
        cls.wifi = AttributeOption.objects.create(attribute=cls.multi, value="Wi-Fi")
        cls.lte = AttributeOption.objects.create(attribute=cls.multi, value="LTE")
        pa = ProductAttribute.objects.create(product=cls.product, attribute=cls.multi)
        pa.options.add(cls.wifi)
        cls.flag = Attribute.objects.create(name="NFC", category=cls.category, kind="boolean")
        ProductAttribute.objects.create(product=cls.product, attribute=cls.flag, boolean_value=False)
        DeliverySettings.objects.create(free_from=2000)

    def get(self, path, params=None, status=200):
        response = self.client.get(path, params or {})
        self.assertEqual(response.status_code, status, response.content[:500])
        return response.json()

    def ids(self, params=None):
        return [item["id"] for item in self.get("/api/catalog", params)["items"]]

    def test_contract_and_both_slash_variants(self):
        for path in ("categories", "catalog", "catalog/filters", "products/popular", "products/limited", "sales", "banners", "tags", f"product/{self.product.pk}", f"product/{self.product.pk}/reviews"):
            with self.subTest(path=path):
                self.assertEqual(self.get("/api/" + path), self.get("/api/" + path + "/"))
        card = self.get("/api/catalog")["items"][0]
        self.assertIsInstance(card["price"], (float, int))
        self.assertEqual(card["count"], 4)
        self.assertTrue(card["images"][0]["src"].endswith("placeholder.svg"))

    def test_text_attribute_search_and_filter(self):
        attribute = Attribute.objects.create(name="Материал", category=self.category, kind="text")
        ProductAttribute.objects.create(product=self.product, attribute=attribute, text_value="Ударопрочный алюминий")
        self.assertEqual(self.ids({f"attributes[{attribute.pk}]": "АЛЮМИНИЙ"}), [self.product.pk])
        self.assertEqual(self.ids({f"attributes[{attribute.pk}]": "пластик"}), [])
        self.assertEqual(self.ids({"filter[name]": "УДАРОПРОЧНЫЙ"}), [])
        self.get('/api/catalog', {f"attributes[{attribute.pk}]": "x" * 501}, status=400)

    def test_categories_two_levels_and_parent_filter(self):
        categories = self.get("/api/categories")
        root = next(item for item in categories if item["id"] == self.root.pk)
        self.assertEqual(root["subcategories"][0]["id"], self.category.pk)
        self.assertEqual(self.ids({"category": self.root.pk}), [self.product.pk])
        self.root.delete()
        self.assertEqual(self.ids(), [])
        self.get("/api/categories")
        self.get(f"/api/product/{self.product.pk}", status=404)

    def test_archived_product_excluded_everywhere(self):
        self.product.delete()
        for path in ("products/popular", "products/limited", "banners", "tags"):
            self.assertEqual(self.get("/api/" + path), [])
        self.assertEqual(self.ids(), [])
        self.get(f"/api/product/{self.product.pk}", status=404)
        self.get(f"/api/product/{self.product.pk}/reviews", status=404)

    def test_unicode_search_in_name_only(self):
        self.assertEqual(self.ids({"filter[name]": "ТЕЛЕФОН"}), [self.product.pk])
        self.product.title = "Товар"
        self.product.save()
        self.assertEqual(self.ids({"filter[name]": "сИНИЙ"}), [])
        self.assertEqual(self.ids({"filter[name]": ".*"}), [])

    def test_all_filter_types_and_combination(self):
        self.assertEqual(self.ids({f"attributes[{self.single.pk}]": self.blue.pk}), [self.product.pk])
        self.assertEqual(self.ids({f"attributes[{self.single.pk}]": self.red.pk}), [])
        self.assertEqual(self.ids({f"attributes[{self.multi.pk}][]": [self.wifi.pk, self.lte.pk]}), [self.product.pk])
        self.assertEqual(self.ids({f"attributes[{self.flag.pk}]": "false"}), [self.product.pk])
        self.assertEqual(self.ids({f"attributes[{self.flag.pk}]": "true"}), [])
        self.assertEqual(self.ids({"filter[manufacturer]": "Издатель"}), [])
        self.assertEqual(self.ids({"filter[manufacturer]": "Марка А", "category": self.root.pk,
                                  f"attributes[{self.single.pk}]": self.blue.pk, "filter[minPrice]": "2500",
                                  "filter[maxPrice]": "2500", "filter[freeDelivery]": "true"}), [self.product.pk])
        filters = self.get("/api/catalog/filters", {"category": self.category.pk})
        self.assertIn(self.single.pk, [item["id"] for item in filters["attributes"]])

    def test_invalid_filters_return_400(self):
        for params in ({"filter[minPrice]": "NaN"}, {"filter[maxPrice]": "Infinity"},
                       {"filter[minPrice]": "-1"}, {"filter[maxPrice]": "0.001"},
                       {"filter[minPrice]": "20", "filter[maxPrice]": "10"}, {"limit": "0"},
                       {"limit": "101"}, {"currentPage": "1.5"}, {"sort": "bad"}, {"sortType": "bad"},
                       {"filter[available]": "yes"}, {"category": "bad"}, {"tags[]": "bad"},
                       {f"attributes[{self.single.pk}]": self.wifi.pk},
                       {f"attributes[{self.single.pk}][]": [self.blue.pk, self.red.pk]},
                       {f"attributes[{self.flag.pk}]": "yes"}, {"attributes[bad]": "yes"}):
            with self.subTest(params=params):
                self.assertIn("errors", self.get("/api/catalog", params, 400))

    def test_pagination_and_empty_results(self):
        self.assertEqual(self.get("/api/catalog", {"filter[name]": "nothing"})["lastPage"], 1)
        data = self.get("/api/catalog", {"filter[available]": "false", "limit": 1, "sort": "price", "sortType": "inc"})
        self.assertEqual(data["items"][0]["id"], self.second.pk)
        self.assertEqual(data["lastPage"], 2)
        self.get("/api/catalog", {"currentPage": 2}, 404)

    def test_price_uses_available_sellers_and_active_largest_discount(self):
        cheap_seller = Seller.objects.create(name="Нет в наличии")
        Offer.objects.create(product=self.product, seller=cheap_seller, price="10", stock=0)
        now = timezone.now()
        for percent, starts, ends in ((10, -1, 1), (20, -1, 1), (99, -3, -1), (90, 1, 2)):
            Discount.objects.create(product=self.product, percent=percent, starts_at=now + timedelta(days=starts), ends_at=now + timedelta(days=ends))
        item = self.get(f"/api/product/{self.product.pk}")
        self.assertEqual(item["price"], 2000)
        self.assertTrue(item["freeDelivery"])
        sale = self.get("/api/sales")["items"][0]
        self.assertEqual((sale["price"], sale["salePrice"]), (2500, 2000))
        self.assertEqual(self.ids({"filter[maxPrice]": "1999.99"}), [])

    def test_expired_discounts_absent_and_decimal_rounding(self):
        now = timezone.now()
        Discount.objects.create(product=self.product, percent=20, starts_at=now - timedelta(days=2), ends_at=now - timedelta(days=1))
        self.assertEqual(self.get("/api/sales")["items"], [])
        self.offer.price = Decimal("99.99"); self.offer.save()
        Discount.objects.create(product=self.product, percent=15, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1))
        self.assertEqual(self.get(f"/api/product/{self.product.pk}")["price"], 84.99)

    def test_archived_seller_and_missing_offer(self):
        self.seller.user = self.user; self.seller.save()
        self.user.delete()
        self.assertEqual(self.ids({"filter[available]": "false"}), [])

    def test_popularity_counts_paid_quantity_without_join_multiplication(self):
        for status, quantity in (("paid", 3), ("new", 100)):
            order = Order.objects.create(user=self.user, full_name="Reader", email=self.user.email, phone="", city="City", address="Street", status=status)
            OrderItem.objects.create(order=order, offer=self.offer, title="Phone", seller_name="Shop", unit_price=2500, quantity=quantity)
        for _ in range(3):
            Review.objects.create(product=self.product, author=self.user, text="Хорошо", rating=4)
        card = self.get("/api/products/popular")[0]
        self.assertEqual((card["purchases"], card["reviews"], card["count"]), (3, 3, 4))
        self.assertEqual(card["rating"], 4)

    def test_popular_and_limited_limits_and_sort_index(self):
        for index in range(20):
            product = Product.objects.create(title=f"Товар {index}", category=self.category, manufacturer="Brand", limited=True, sort_index=index + 1)
            Offer.objects.create(product=product, seller=self.seller, price=100, stock=1)
        self.assertEqual(len(self.get("/api/products/popular")), 8)
        self.assertEqual(len(self.get("/api/products/limited")), 16)
        self.assertEqual(self.get("/api/products/popular")[0]["id"], self.product.pk)

    def test_reviews_pagination_and_guest_rejection(self):
        for index in range(7):
            Review.objects.create(product=self.product, author=self.user, text=f"Отзыв {index}", rating=4)
        detail = self.get(f"/api/product/{self.product.pk}")
        self.assertEqual(len(detail["reviews"]), 5)
        self.assertEqual(detail["reviewCount"], 7)
        second = self.get(f"/api/product/{self.product.pk}/reviews", {"currentPage": 2})
        self.assertEqual(len(second["items"]), 2)
        self.assertFalse(set(item["id"] for item in detail["reviews"]) & set(item["id"] for item in second["items"]))
        response = self.client.post(f"/api/product/{self.product.pk}/reviews", {"text": "Hello", "rate": 5}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_review_validation_and_author_cannot_be_forged(self):
        self.client.force_login(self.user)
        url = f"/api/product/{self.product.pk}/reviews"
        for payload in ({"text": " ", "rate": 5}, {"text": "Good", "rate": 6}, {"text": "Good", "rate": True}, [], {"text": "x" * 5001, "rate": 5}):
            self.assertEqual(self.client.post(url, payload, content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(url, 'broken', content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(url, {"text": "Hello"}).status_code, 415)
        response = self.client.post(url, {"text": "  Отлично  ", "rate": "5", "author": "Другой", "email": "other@example.com"}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["author"], "Читатель")
        self.assertEqual(Review.objects.get().text, "Отлично")

    def test_csrf_required_and_authenticated_session_works(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = f"/api/product/{self.product.pk}/reviews"
        self.assertEqual(client.post(url, {"text": "Good", "rate": 5}, content_type="application/json").status_code, 403)
        client.get(f"/product/{self.product.pk}/")
        token = client.cookies["csrftoken"].value
        self.assertEqual(client.post(url, {"text": "Good", "rate": 5}, content_type="application/json", HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_template_and_static_overrides_selected(self):
        from django.contrib.staticfiles import finders
        for url, template in (("/", "index"), ("/catalog/", "catalog"), (f"/product/{self.product.pk}/", "product"), ("/sale/", "sale")):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, f"frontend/{template}.html")
            self.assertContains(response, "lavka/shop.js")
            self.assertNotContains(response, "unpkg.com")
        self.assertIsNotNone(finders.find("lavka/shop.js"))
        self.assertIsNotNone(finders.find("catalog/placeholder.svg"))

    def test_query_count_does_not_grow_per_product(self):
        for index in range(10):
            product = Product.objects.create(title=f"Item {index}", category=self.category, manufacturer="Brand")
            Offer.objects.create(product=product, seller=self.seller, price=100, stock=1)
        with self.assertNumQueries(4):
            self.get("/api/catalog")

    def test_methods_and_unknown_ids(self):
        self.assertEqual(self.client.post("/api/catalog").status_code, 405)
        self.get("/api/product/999999", status=404)
        self.get("/api/product/999999999999999999999999999", status=400)
        self.get("/api/catalog", {"category": 999999}, 404)
