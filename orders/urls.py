from django.urls import re_path
from . import api

urlpatterns = [
    re_path(r"^checkout/?$", api.checkout),
    re_path(r"^checkout/register/?$", api.register_checkout),
    re_path(r"^orders/?$", api.orders),
    re_path(r"^orders?/(?P<pk>[0-9]+)/?$", api.detail),
    re_path(r"^payment/(?P<pk>[0-9]+)/?$", api.payment),
    re_path(r"^account/?$", api.account),
]
