from django.contrib import admin
from django import forms
from core.admin import SoftDeleteAdmin
from .models import Category, Product, ProductImage, Seller, Offer, Review, Discount, Attribute, AttributeOption, ProductAttribute


@admin.register(Category)
class CategoryAdmin(SoftDeleteAdmin):
    list_display = ("name", "parent", "deleted_at")
    search_fields = ("name",)


class OfferInline(admin.TabularInline):
    model = Offer
    extra = 0


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(SoftDeleteAdmin):
    list_display = ("title", "category", "manufacturer", "limited", "deleted_at")
    list_filter = ("category", "limited", "deleted_at")
    search_fields = ("title", "manufacturer")
    inlines = (OfferInline, ProductImageInline)


@admin.register(Discount)
class DiscountAdmin(admin.ModelAdmin):
    list_display = ("product", "percent", "starts_at", "ends_at")
    list_select_related = ("product",)
    search_fields = ("product__title",)


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("product", "seller", "price", "stock")
    list_select_related = ("product", "seller")
    search_fields = ("product__title", "seller__name")


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "author", "rating", "created_at")
    list_select_related = ("product", "author")
    search_fields = ("product__title", "author__username")


admin.site.register(Seller)


class ProductAttributeForm(forms.ModelForm):
    class Meta:
        model = ProductAttribute
        fields = "__all__"

    def clean(self):
        data = super().clean()
        attribute, options = data.get("attribute"), data.get("options")
        if attribute and options is not None:
            if options.exclude(attribute=attribute).exists():
                self.add_error("options", "Выбраны значения другой характеристики.")
            count = options.count()
            if attribute.kind == Attribute.Kind.SINGLE and count != 1:
                self.add_error("options", "Выберите одно значение.")
            if attribute.kind == Attribute.Kind.MULTIPLE and not count:
                self.add_error("options", "Выберите хотя бы одно значение.")
            if attribute.kind in (Attribute.Kind.BOOLEAN, Attribute.Kind.TEXT) and count:
                self.add_error("options", "Для галочки и текста варианты не используются.")
        return data


@admin.register(ProductAttribute)
class ProductAttributeAdmin(admin.ModelAdmin):
    form = ProductAttributeForm


admin.site.register([Attribute, AttributeOption])
