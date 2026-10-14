from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [migrations.CreateModel(name="WorkerHeartbeat", fields=[
        ("name", models.CharField(max_length=64, primary_key=True, serialize=False)),
        ("last_seen", models.DateTimeField()),
    ])]
