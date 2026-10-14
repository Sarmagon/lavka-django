from django.urls import re_path
from . import api, commerce_api

app_name = "catalog"
urlpatterns = [
    re_path(r"^categories/?$", api.categories, name="categories"),
    re_path(r"^catalog/?$", api.catalog, name="catalog"),
    re_path(r"^catalog/filters/?$", api.filters, name="filters"),
    re_path(r"^products/popular/?$", api.popular, name="popular"),
    re_path(r"^products/limited/?$", api.limited, name="limited"),
    re_path(r"^sales/?$", api.sales, name="sales"),
    re_path(r"^banners/?$", api.banners, name="banners"),
    re_path(r"^tags/?$", api.tags, name="tags"),
    re_path(r"^product/(?P<pk>[0-9]+)/?$", api.detail, name="product"),
    re_path(r"^product/(?P<pk>[0-9]+)/reviews?/?$", api.reviews, name="reviews"),
    re_path(r"^(?:sign-in)/?$", commerce_api.sign_in, name="sign-in"),
    re_path(r"^(?:sign-up)/?$", commerce_api.sign_up, name="sign-up"),
    re_path(r"^(?:sign-out)/?$", commerce_api.sign_out, name="sign-out"),
    re_path(r"^basket/?$", commerce_api.basket, name="basket"),
    re_path(r"^profile/?$", commerce_api.profile, name="profile"),
    re_path(r"^profile/password/?$", commerce_api.profile_password, name="profile-password"),
    re_path(r"^profile/avatar/?$", commerce_api.profile_avatar, name="profile-avatar"),
]
