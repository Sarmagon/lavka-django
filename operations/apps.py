from django.apps import AppConfig


class OperationsConfig(AppConfig):
    name = "operations"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from prometheus_client import REGISTRY
        from operations.metrics import PaymentCollector
        REGISTRY.register(PaymentCollector())
