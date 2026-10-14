from django.db import migrations


def forward(apps, schema_editor):
    apps.get_model("orders", "DeliverySettings").objects.using(schema_editor.connection.alias).create(pk=1)


def backward(apps, schema_editor):
    apps.get_model("orders", "DeliverySettings").objects.using(schema_editor.connection.alias).filter(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [("orders", "0001_initial")]
    operations = [migrations.RunPython(forward, backward)]
