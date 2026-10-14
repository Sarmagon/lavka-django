from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import User
from accounts.admin import AccountAdmin
from catalog.admin import ProductAdmin
from .models import Category, Product, Seller, Offer, Review
from orders.models import Order, OrderItem


class ModelTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Техника")
        self.product = Product.objects.create(title="Телефон", category=self.category, manufacturer="Марка")
        self.user = User.objects.create_user(username="buyer", email="buyer@example.com", full_name="Иван Иванов", password="test-password")
        self.seller = Seller.objects.create(name="Магазин")
        self.offer = Offer.objects.create(product=self.product, seller=self.seller, price=Decimal("100"), stock=5)

    def test_category_depth_and_cycles(self):
        child = Category.objects.create(name="Телефоны", parent=self.category)
        with self.assertRaises(ValidationError):
            Category(name="Третий уровень", parent=child).full_clean()
        self.category.parent = child
        with self.assertRaises(ValidationError):
            self.category.full_clean()

    def test_cannot_move_parent_to_second_level(self):
        Category.objects.create(name="Телефоны", parent=self.category)
        self.category.parent = Category.objects.create(name="Другая")
        with self.assertRaises(ValidationError):
            self.category.full_clean()

    def test_email_uniqueness_in_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="other", email="BUYER@example.com", full_name="Другой")

    def test_phone_normalization_and_validation(self):
        self.user.phone = "+7 (999) 123-45-67"
        self.user.save()
        self.assertEqual(self.user.phone, "+79991234567")
        self.user.phone = "abc"
        with self.assertRaises(ValidationError):
            self.user.full_clean()

    def test_multiple_empty_phones(self):
        User.objects.create_user(username="other", email="other@example.com", full_name="Другой")
        self.assertIsNone(self.user.phone)

    def test_admin_bulk_user_delete_disables_login(self):
        AccountAdmin(User, AdminSite()).delete_queryset(None, User.objects.filter(pk=self.user.pk))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertIsNotNone(self.user.deleted_at)
        self.assertFalse(self.client.login(username="buyer", password="test-password"))

    def test_admin_product_delete_preserves_offer(self):
        ProductAdmin(Product, AdminSite()).delete_queryset(None, Product.objects.filter(pk=self.product.pk))
        self.product.refresh_from_db()
        self.assertIsNotNone(self.product.deleted_at)
        self.assertTrue(Offer.objects.filter(pk=self.offer.pk).exists())

    def test_category_delete_preserves_product(self):
        self.category.delete()
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
        self.category.refresh_from_db()
        self.assertIsNotNone(self.category.deleted_at)

    def test_database_rejects_bad_price_and_rating(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Offer.objects.filter(pk=self.offer.pk).update(price=-1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(product=self.product, author=self.user, rating=6, text="Текст")

    def test_order_keeps_snapshot_and_soft_delete(self):
        order = Order.objects.create(user=self.user, full_name="Иван", email=self.user.email, phone="+79991234567", city="Москва", address="Улица")
        item = OrderItem.objects.create(order=order, offer=self.offer, title="Телефон", seller_name="Магазин", unit_price=100, quantity=2)
        self.offer.price = 500
        self.offer.save()
        item.refresh_from_db()
        self.assertEqual(item.unit_price, 100)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrderItem.objects.filter(pk=item.pk).update(quantity=0)
        order.delete()
        self.assertTrue(OrderItem.objects.filter(pk=item.pk).exists())

    def test_initial_roles_and_admin(self):
        from django.contrib.auth.models import Group
        self.assertTrue(User.objects.get(username="admin").is_superuser)
        self.assertEqual(Group.objects.filter(name__in=["Покупатели", "Продавцы", "Менеджеры"]).count(), 3)

    def test_admin_confirmation_and_delete_with_protected_relations(self):
        self.client.force_login(User.objects.get(username="admin"))
        url = f"/admin/catalog/product/{self.product.pk}/delete/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["protected"])
        self.assertIsNone(Product.objects.get(pk=self.product.pk).deleted_at)
        response = self.client.post(url, {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(Product.objects.get(pk=self.product.pk).deleted_at)
        self.assertTrue(Offer.objects.filter(pk=self.offer.pk).exists())

    def test_image_contents_and_size(self):
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.validators import validate_image
        with self.assertRaises(ValidationError):
            validate_image(SimpleUploadedFile("fake.png", b"not an image"))
        with self.assertRaises(ValidationError):
            validate_image(SimpleUploadedFile("large.png", b"x" * (2 * 1024 * 1024 + 1)))
        stream = BytesIO()
        Image.new("RGB", (2, 2)).save(stream, format="PNG")
        upload = SimpleUploadedFile("valid.png", stream.getvalue())
        validate_image(upload)
        self.assertEqual(upload.tell(), 0)

    def test_attribute_form_rejects_wrong_options(self):
        from .models import Attribute, AttributeOption
        from .admin import ProductAttributeForm
        attribute = Attribute.objects.create(name="Цвет", category=self.category, kind="single")
        other = Attribute.objects.create(name="Память", category=self.category, kind="single")
        option = AttributeOption.objects.create(attribute=other, value="128 ГБ")
        form = ProductAttributeForm(data={"product": self.product.pk, "attribute": attribute.pk, "options": [option.pk]})
        self.assertFalse(form.is_valid())
        self.assertIn("options", form.errors)

    def test_archive_action_is_visible_and_preserves_relations(self):
        self.client.force_login(User.objects.get(username="admin"))
        url = "/admin/catalog/product/"
        response = self.client.get(url)
        self.assertContains(response, "Архивировать выбранные записи")
        self.assertNotContains(response, 'value="delete_selected"')
        response = self.client.post(url, {
            "action": "archive_selected", "_selected_action": [self.product.pk], "index": 0,
        })
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertIsNotNone(self.product.deleted_at)
        self.assertTrue(Offer.objects.filter(pk=self.offer.pk).exists())

    def test_archive_user_action_disables_login(self):
        self.client.force_login(User.objects.get(username="admin"))
        response = self.client.post("/admin/accounts/user/", {
            "action": "archive_selected", "_selected_action": [self.user.pk], "index": 0,
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertIsNotNone(self.user.deleted_at)

    def test_discount_admin_shows_product_and_percent(self):
        from django.utils import timezone
        from datetime import timedelta
        from .models import Discount
        discount = Discount.objects.create(product=self.product, percent=10,
            starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=1))
        self.assertEqual(str(discount), "Телефон — скидка 10%")
        self.client.force_login(User.objects.get(username="admin"))
        response = self.client.get("/admin/catalog/discount/")
        self.assertContains(response, "Телефон")
        self.assertNotContains(response, "Discount object")


class FixtureTests(TestCase):
    def test_demo_fixture_and_password(self):
        from django.core.management import call_command
        call_command("loaddata", "demo", verbosity=0)
        self.assertTrue(User.objects.get(username="buyer").check_password("123456"))
        self.assertEqual(Product.objects.filter(pk__gte=1001).count(), 18)
        self.assertEqual(Offer.objects.filter(pk__gte=1001).count(), 36)
