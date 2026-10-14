from django.test import TestCase, Client
from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.staticfiles import finders
from catalog.models import Product

class LavkaTests(TestCase):
    def test_empty_store_loads_without_supplied_package(self):
        for url in ["/", "/catalog/", "/sale/", "/cart/", "/sign-in/", "/sign-up/"]:
            response=self.client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertContains(response,"лавка")
            self.assertContains(response,"lavka/shop.js")
            self.assertNotContains(response,"vue.global.js")
    def test_seed_images_and_discounts(self):
        call_command("seed_lavka",verbosity=0)
        data=self.client.get("/api/catalog").json()
        self.assertEqual(data["total"],12)
        self.assertEqual(len({p["images"][0]["src"] for p in data["items"]}),3)
        self.assertTrue(all(p["images"][0]["sheet"] for p in data["items"]))
        self.assertEqual(self.client.get("/api/sales").json()["total"],3)
        self.assertEqual(self.client.get("/api/catalog",{"name":"Кружка"}).json()["total"],1)
    def test_seed_refuses_to_overwrite(self):
        call_command("seed_lavka",verbosity=0)
        with self.assertRaises(CommandError):call_command("seed_lavka",verbosity=0)
        self.assertEqual(Product.objects.count(),12)
    def test_unknown_product_is_404(self):
        self.assertEqual(self.client.get("/product/999999/").status_code,404)
    def test_static_assets_present(self):
        for name in ["lavka/shop.js","lavka/shop.css","lavka-products.png","lavka-products-2.png","lavka-products-3.png"]:
            self.assertIsNotNone(finders.find(name))
    def test_page_provides_csrf_but_api_does_not_bypass_it(self):
        client=Client(enforce_csrf_checks=True)
        client.get("/cart/")
        self.assertIn("csrftoken",client.cookies)
        self.assertEqual(client.post("/api/basket",{},content_type="application/json").status_code,403)
