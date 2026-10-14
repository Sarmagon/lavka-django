import struct
import zlib
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.contrib.auth.models import Group

from accounts.models import User
from orders.models import DeliverySettings
from .models import Category, Offer, Product, Seller


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CustomerAndBasketTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Телефоны")
        cls.seller = Seller.objects.create(name="Магазин")
        cls.product = Product.objects.create(title="Телефон", category=cls.category, manufacturer="Марка")
        cls.offer = Offer.objects.create(product=cls.product, seller=cls.seller, price="1000", stock=2)
        DeliverySettings.objects.create(free_from=2000)
        cls.user = User.objects.create_user(username="buyer", full_name="Покупатель Тестовый",
                                            email="buyer@example.com", password="Test-password-907!")
        Group.objects.get_or_create(name="Покупатели")

    @staticmethod
    def png_bytes():
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
        header = struct.pack(">2I5B", 1, 1, 8, 6, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\xff")) + chunk(b"IEND", b""))

    def json_post(self, path, data, **kwargs):
        return self.client.post(path, data, content_type="application/json", **kwargs)

    def test_signup_validates_and_authenticates_new_customer(self):
        invalid = self.json_post("/api/sign-up", {"name": "Тест", "username": "new", "email": "bad", "password": "x"})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("email", invalid.json()["errors"])
        response = self.json_post("/api/sign-up", {"name": "Новый клиент", "username": "new", "email": "NEW@example.com", "password": "Long-password-123!"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["user"]["email"], "new@example.com")
        self.assertTrue(self.client.session.get("_auth_user_id"))
        self.assertTrue(User.objects.get(username="new").groups.filter(name="Покупатели").exists())
        duplicate = self.json_post("/api/sign-up", {"name": "Другой", "username": "NEW", "email": "other@example.com", "password": "Long-password-123!"})
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("username", duplicate.json()["errors"])

    def test_signin_rejects_invalid_password_and_signout_ends_session(self):
        bad = self.json_post("/api/sign-in", {"username": "buyer", "password": "wrong"})
        self.assertEqual(bad.status_code, 401)
        good = self.json_post("/api/sign-in", {"username": "buyer", "password": "Test-password-907!"})
        self.assertEqual(good.status_code, 200)
        self.assertEqual(self.client.get("/api/profile").status_code, 200)
        self.assertEqual(self.json_post("/api/sign-out", {}).status_code, 200)
        self.assertEqual(self.client.get("/api/profile").status_code, 401)

    def test_profile_requires_auth_and_validates_all_fields(self):
        self.assertEqual(self.client.get("/api/profile").status_code, 401)
        self.assertRedirects(self.client.get("/profile/"), "/sign-in/?next=/profile/", fetch_redirect_response=False)
        self.client.force_login(self.user)
        response = self.client.get("/api/profile")
        self.assertEqual(response.json()["fullName"], "Покупатель Тестовый")
        invalid = self.json_post("/api/profile", {"fullName": "Имя", "email": "bad", "phone": "123"})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("email", invalid.json()["errors"])
        invalid_phone = self.json_post("/api/profile", {"fullName": "Имя", "email": "buyer@example.com", "phone": "123"})
        self.assertEqual(invalid_phone.status_code, 400)
        self.assertIn("phone", invalid_phone.json()["errors"])
        User.objects.create_user(username="other", full_name="Другой", email="other@example.com",
                                  phone="+79991234568", password="Other-password-123!")
        duplicate_phone = self.json_post("/api/profile", {"fullName": "Имя", "email": "buyer@example.com", "phone": " +7 (999) 123-45-68 "})
        self.assertEqual(duplicate_phone.status_code, 400)
        self.assertIn("phone", duplicate_phone.json()["errors"])
        valid = self.json_post("/api/profile", {"fullName": "Новое имя", "email": " BUYER@example.com ", "phone": "+79991234567"})
        self.assertEqual(valid.status_code, 200, valid.content)
        self.user.refresh_from_db()
        self.assertEqual((self.user.full_name, self.user.email, self.user.phone), ("Новое имя", "buyer@example.com", "+79991234567"))

    def test_password_change_checks_current_password_and_strength(self):
        self.client.force_login(self.user)
        wrong = self.json_post("/api/profile/password", {"currentPassword": "wrong", "newPassword": "Long-password-111!"})
        self.assertEqual(wrong.status_code, 400)
        weak = self.json_post("/api/profile/password", {"currentPassword": "Test-password-907!", "newPassword": "123"})
        self.assertEqual(weak.status_code, 400)
        good = self.json_post("/api/profile/password", {"currentPassword": "Test-password-907!", "newPassword": "Another-strong-567!"})
        self.assertEqual(good.status_code, 200, good.content)
        self.assertEqual(self.client.get("/api/profile").status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Another-strong-567!"))

    def test_avatar_accepts_real_image_and_rejects_invalid_file(self):
        self.client.force_login(self.user)
        invalid = SimpleUploadedFile("avatar.png", b"not an image", content_type="image/png")
        response = self.client.post("/api/profile/avatar", {"avatar": invalid})
        self.assertEqual(response.status_code, 400)
        self.assertIn("avatar", response.json()["errors"])
        png = self.png_bytes()
        valid = SimpleUploadedFile("avatar.png", png, content_type="image/png")
        response = self.client.post("/api/profile/avatar", {"avatar": valid})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(self.client.get("/api/profile").json()["avatar"]["src"].endswith(".png"))
        removed = self.client.delete("/api/profile/avatar")
        self.assertEqual(removed.status_code, 200)
        self.assertIsNone(self.client.get("/api/profile").json()["avatar"])

    def test_guest_basket_persists_through_login_and_enforces_stock(self):
        added = self.json_post("/api/basket", {"id": self.product.pk, "count": 1})
        self.assertEqual(added.status_code, 200, added.content)
        self.assertEqual(added.json()[0]["count"], 1)
        self.json_post("/api/sign-in", {"username": "buyer", "password": "Test-password-907!"})
        current = self.client.get("/api/basket").json()
        self.assertEqual(current[0]["id"], self.product.pk)
        self.json_post("/api/sign-out", {})
        self.assertEqual(self.client.get("/api/basket").json()[0]["count"], 1)
        exceeded = self.json_post("/api/basket", {"id": self.product.pk, "count": 2})
        self.assertEqual(exceeded.status_code, 409)
        self.assertEqual(self.client.get("/api/basket").json()[0]["count"], 1)
        reduced = self.client.delete("/api/basket", data='{"id": %s, "count": 1}' % self.product.pk, content_type="application/json")
        self.assertEqual(reduced.status_code, 200)
        self.assertEqual(reduced.json(), [])

    def test_basket_rejects_bad_quantity_and_missing_product(self):
        bad_count = self.json_post("/api/basket", {"id": self.product.pk, "count": 0})
        self.assertEqual(bad_count.status_code, 400)
        missing = self.json_post("/api/basket", {"id": 999999, "count": 1})
        self.assertEqual(missing.status_code, 404)
