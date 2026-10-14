from django.urls import path
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from catalog.models import Product

@ensure_csrf_cookie
def page(request, screen="index", id=None):
    if id is not None:
        get_object_or_404(Product.objects.alive(), pk=id)
    return render(request, f"frontend/{screen}.html", {"product_id": id})

urlpatterns = [
    path("", page), path("catalog/", page, {"screen": "catalog"}),
    path("sale/", page, {"screen": "sale"}), path("cart/", page, {"screen": "cart"}),
    path("product/<int:id>/", page, {"screen": "product"}),
    path("sign-in/", page, {"screen": "signIn"}), path("sign-up/", page, {"screen": "signUp"}),
]
