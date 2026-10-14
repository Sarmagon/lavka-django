from hmac import compare_digest
from django.conf import settings
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django_prometheus.exports import ExportToDjangoView


@require_GET
@never_cache
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


@require_GET
@never_cache
def metrics(request):
    token = settings.METRICS_TOKEN
    if not token or not compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
        return JsonResponse({"error": "forbidden"}, status=403)
    return ExportToDjangoView(request)
