import time
from django.core.management.base import BaseCommand
from django.db import OperationalError, close_old_connections
from orders.payment_worker import process_one
from django.utils import timezone
from operations.models import WorkerHeartbeat


class Command(BaseCommand):
    help = "Обработчик очереди учебных платежей"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        self.stdout.write("Обработчик оплаты запущен.")
        last_heartbeat = 0
        try:
            while True:
                close_old_connections()
                try:
                    if time.monotonic() - last_heartbeat >= 10:
                        WorkerHeartbeat.objects.update_or_create(name="payment", defaults={"last_seen": timezone.now()})
                        last_heartbeat = time.monotonic()
                    worked = process_one()
                except OperationalError:
                    worked = False
                if options["once"]:
                    return
                if not worked:
                    time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write("Обработчик остановлен.")
