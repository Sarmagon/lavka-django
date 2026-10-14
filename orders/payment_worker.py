import json
import logging
from datetime import timedelta
from urllib.request import Request, urlopen
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Order, PaymentJob


def payment_service(job):
    request = Request(settings.PAYMENT_SERVICE_URL, method="POST",
        data=json.dumps({"key": str(job.key), "number": job.number}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + settings.PAYMENT_SERVICE_TOKEN})
    with urlopen(request, timeout=10) as response:
        result = json.load(response)
    if not isinstance(result, dict) or type(result.get("success")) is not bool:
        raise ValueError("Некорректный ответ сервиса")
    return result


def process_one(transport=payment_service):
    now, token = timezone.now(), uuid4()
    eligible = Q(state="queued", lease_until__isnull=True) | Q(state="queued", lease_until__lte=now) | Q(state="running", lease_until__lte=now)
    job = PaymentJob.objects.filter(eligible).order_by("pk").first()
    if not job:
        return False
    # Atomic conditional claim also works on SQLite where SELECT FOR UPDATE is a no-op.
    if not PaymentJob.objects.filter(eligible, pk=job.pk).update(state="running", lease_until=now + timedelta(seconds=60), lease_token=token):
        return True
    job.refresh_from_db()
    try:
        result = transport(job)
        success = result["success"]
        error = "" if success else str(result.get("error") or "Платёж отклонён.")[:500]
    except Exception:
        logging.getLogger(__name__).exception("Payment service request failed")
        with transaction.atomic():
            locked = PaymentJob.objects.select_for_update().get(pk=job.pk)
            if locked.lease_token != token or locked.state != "running":
                return True
            locked.retries += 1
            if locked.retries < 3:
                locked.state, locked.lease_until = "queued", timezone.now() + timedelta(seconds=5 * locked.retries)
                locked.save(update_fields=["retries", "state", "lease_until"])
                return True
        success, error = False, "Сервис оплаты недоступен. Попробуйте оплатить позже."
    with transaction.atomic():
        locked = PaymentJob.objects.select_for_update().get(pk=job.pk)
        if locked.lease_token != token or locked.state != "running":
            return True
        order = Order.objects.select_for_update().get(pk=job.order_id)
        if order.status != Order.Status.PAID:
            order.status = Order.Status.PAID if success else Order.Status.FAILED
            order.payment_error = error
            order.save(update_fields=["status", "payment_error"])
        locked.state, locked.error, locked.finished_at, locked.number = "done", error, timezone.now(), ""
        locked.save(update_fields=["state", "error", "finished_at", "number"])
    return True
