from django.db import DatabaseError
from django.db.models import Count, Min
from django.utils import timezone
from prometheus_client.core import GaugeMetricFamily
from operations.models import WorkerHeartbeat
from orders.models import PaymentJob


class PaymentCollector:
    def describe(self):
        # Registration must not query the database before migrations.
        return []

    def collect(self):
        available = GaugeMetricFamily("megano_queue_database_up", "Payment metrics database available")
        try:
            rows = list(PaymentJob.objects.values("state").annotate(count=Count("pk"), oldest=Min("created_at")))
            heartbeat = WorkerHeartbeat.objects.filter(name="payment").values_list("last_seen", flat=True).first()
        except DatabaseError:
            available.add_metric([], 0)
            yield available
            return
        available.add_metric([], 1)
        yield available
        now = timezone.now()
        counts = GaugeMetricFamily("megano_payment_jobs", "Payment jobs by state", labels=["state"])
        ages = GaugeMetricFamily("megano_payment_oldest_pending_seconds", "Age of oldest active payment")
        pending = []
        for state in ("queued", "running", "done"):
            row = next((r for r in rows if r["state"] == state), None)
            counts.add_metric([state], row["count"] if row else 0)
            if row and state != "done":
                pending.append(max(0, (now - row["oldest"]).total_seconds()))
        ages.add_metric([], max(pending, default=0))
        worker = GaugeMetricFamily("megano_payment_worker_up", "Worker heartbeat received within 45 seconds")
        worker.add_metric([], int(heartbeat is not None and (now - heartbeat).total_seconds() < 45))
        yield counts
        yield ages
        yield worker
