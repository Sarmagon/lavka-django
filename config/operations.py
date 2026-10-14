"""Optional integrations; keep the local installation usable without cloud accounts."""
import os
from django.core.exceptions import ImproperlyConfigured


def configure_operations(settings):
    settings["INSTALLED_APPS"] += ["operations", "django_prometheus"]
    settings["MIDDLEWARE"] = [
        "django_prometheus.middleware.PrometheusBeforeMiddleware",
        *settings["MIDDLEWARE"],
        "django_prometheus.middleware.PrometheusAfterMiddleware",
    ]
    settings["DATABASES"]["default"]["ENGINE"] = "django_prometheus.db.backends.sqlite3"
    settings["METRICS_TOKEN"] = os.getenv("METRICS_TOKEN", "")
    settings["PROMETHEUS_EXPORT_MIGRATIONS"] = False
    settings["MEDIA_STORAGE"] = os.getenv("MEDIA_STORAGE", "local")
    local = {"BACKEND": "django.core.files.storage.FileSystemStorage",
             "OPTIONS": {"location": settings["MEDIA_ROOT"], "base_url": settings["MEDIA_URL"]}}
    settings["STORAGES"] = {
        "default": local,
        "local_media": local,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    bucket = os.getenv("S3_BUCKET_NAME", "")
    if settings["MEDIA_STORAGE"] not in ("local", "s3"):
        raise ImproperlyConfigured("MEDIA_STORAGE must be local or s3")
    if settings["MEDIA_STORAGE"] == "s3" and not bucket:
        raise ImproperlyConfigured("S3_BUCKET_NAME is required for S3 storage")
    if bucket:
        options = {
            "bucket_name": bucket, "location": "media", "default_acl": None,
            "file_overwrite": False, "querystring_auth": True, "querystring_expire": 3600,
            "region_name": os.getenv("S3_REGION_NAME", "us-east-1"),
            "addressing_style": os.getenv("S3_ADDRESSING_STYLE", "path"),
            "signature_version": "s3v4",
        }
        for option, env in (("endpoint_url", "S3_ENDPOINT_URL"),
                            ("access_key", "S3_ACCESS_KEY_ID"), ("secret_key", "S3_SECRET_ACCESS_KEY")):
            if os.getenv(env):
                options[option] = os.environ[env]
        settings["STORAGES"]["object_media"] = {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": options}
        if settings["MEDIA_STORAGE"] == "s3":
            settings["STORAGES"]["default"] = settings["STORAGES"]["object_media"]
    dsn = os.getenv("SENTRY_DSN", "")
    if dsn:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        from operations.sentry import scrub_event
        sentry_sdk.init(
            dsn=dsn, integrations=[DjangoIntegration()], send_default_pii=False,
            include_local_variables=False, max_request_body_size="never",
            traces_sample_rate=0.0, environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
            release=os.getenv("SENTRY_RELEASE") or None, before_send=scrub_event,
        )
