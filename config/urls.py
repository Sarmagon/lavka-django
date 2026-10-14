"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from catalog.views import ProfileView
from orders.views import CheckoutView, CustomerView
from operations.views import health, metrics

urlpatterns = [
    path("health/", health),
    path("metrics/", metrics),
    path("api/", include("orders.urls")),
    path("checkout/", CheckoutView.as_view()),
    path("account/", CustomerView.as_view(template_name="frontend/account.html")),
    path("history-order/", CustomerView.as_view(template_name="frontend/historyorder.html")),
    path("orders/<int:id>/", CustomerView.as_view(template_name="frontend/oneorder.html")),
    path("order-detail/<int:id>/", CustomerView.as_view(template_name="frontend/oneorder.html")),
    path("payment/<int:id>/", CustomerView.as_view(template_name="frontend/payment.html")),
    path("payment-someone/", CustomerView.as_view(template_name="frontend/paymentsomeone.html")),
    path("progress-payment/", CustomerView.as_view(template_name="frontend/progressPayment.html")),
    path("api/", include("catalog.urls")),
    path("profile/", ProfileView.as_view()),
    path("", include("storefront_ui.urls")),
    path('admin/', admin.site.urls),
]

from django.conf import settings
from django.conf.urls.static import static

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
