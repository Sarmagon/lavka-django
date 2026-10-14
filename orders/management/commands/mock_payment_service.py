from http.server import ThreadingHTTPServer
from django.conf import settings
from django.core.management.base import BaseCommand
from orders.mock_payment import handler


class Command(BaseCommand):
    help = "Локальный фиктивный сервис оплаты; реальные карты не используются"

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", default=8001, type=int)

    def handle(self, *args, **options):
        server = ThreadingHTTPServer((options["host"], options["port"]), handler(settings.PAYMENT_SERVICE_TOKEN, settings.PAYMENT_SERVICE_DB))
        self.stdout.write("Учебный сервис оплаты запущен.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
