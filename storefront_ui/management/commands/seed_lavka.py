from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from catalog.models import Category, Product, Offer, Seller, Attribute, AttributeOption, ProductAttribute, Discount
from storefront_ui.products import DEMO_PRODUCTS

class Command(BaseCommand):
    help = "Create twelve fictional Lavka demo products in an empty catalogue. Never overwrites existing products."

    @transaction.atomic
    def handle(self, *args, **options):
        if Product.objects.exists():
            raise CommandError("Каталог не пуст. Демо не загружено: существующие товары сохранены.")
        categories={name:Category.objects.create(name=name) for name in dict.fromkeys(row[1] for row in DEMO_PRODUCTS)}
        sellers=[Seller.objects.create(name="Лавка · основной демо-продавец"),Seller.objects.create(name="Лавка · второй демо-продавец")]
        attrs={}
        for name,cat in categories.items():
            attrs[name]=[Attribute.objects.create(category=cat,name="Материал",kind="single"),Attribute.objects.create(category=cat,name="Цвет",kind="text"),Attribute.objects.create(category=cat,name="Для рабочего стола",kind="boolean")]
        for index,(title,category,description,price,material,color) in enumerate(DEMO_PRODUCTS):
            product=Product.objects.create(title=title,category=categories[category],description=description,manufacturer="Лавка · демо",sort_index=index,limited=index in [0,4])
            for n,seller in enumerate(sellers):Offer.objects.create(product=product,seller=seller,price=Decimal(price)+n*100,stock=20-n*5)
            single,text,boolean=attrs[category]
            option,_=AttributeOption.objects.get_or_create(attribute=single,value=material)
            item=ProductAttribute.objects.create(product=product,attribute=single);item.options.add(option)
            ProductAttribute.objects.create(product=product,attribute=text,text_value=color)
            ProductAttribute.objects.create(product=product,attribute=boolean,boolean_value=True)
            if index in [1,5,9]:Discount.objects.create(product=product,percent=10,starts_at=timezone.now()-timedelta(days=1),ends_at=timezone.now()+timedelta(days=30))
        self.stdout.write(self.style.SUCCESS("Создано 12 вымышленных товаров, 3 категории и 2 демо-продавца. Реальных продаж нет."))
