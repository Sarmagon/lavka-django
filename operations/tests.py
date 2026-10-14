import tempfile
import io
import os
from pathlib import Path
from unittest.mock import patch
from datetime import timedelta
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import OperationalError
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from operations.media import copy_verified
from operations.models import WorkerHeartbeat
from operations.sentry import scrub_event
from config.operations import configure_operations
from django.core.management import call_command
from django.core.management.base import CommandError
from dotenv import dotenv_values


class MonitoringTests(TestCase):
    def test_health_checks_database_and_hides_error(self):
        self.assertEqual(self.client.get("/health/").json(), {"status": "ok"})
        with patch("operations.views.connection.cursor", side_effect=OperationalError("secret connection")):
            response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "secret", status_code=503)

    @override_settings(METRICS_TOKEN="")
    def test_metrics_disabled_without_token_even_for_staff(self):
        self.assertEqual(self.client.get("/metrics/").status_code, 403)

    @override_settings(METRICS_TOKEN="test-metrics-key")
    def test_metrics_auth_database_and_stale_worker(self):
        self.assertEqual(self.client.get("/metrics/", HTTP_AUTHORIZATION="Bearer wrong").status_code, 403)
        WorkerHeartbeat.objects.create(name="payment", last_seen=timezone.now() - timedelta(minutes=2))
        response = self.client.get("/metrics/", HTTP_AUTHORIZATION="Bearer test-metrics-key")
        self.assertContains(response, "megano_payment_worker_up 0.0")
        self.assertContains(response, 'megano_payment_jobs{state="queued"} 0.0')
        self.assertContains(response, "django_db_execute_total")
        WorkerHeartbeat.objects.filter(name="payment").update(last_seen=timezone.now())
        self.assertContains(self.client.get("/metrics/", HTTP_AUTHORIZATION="Bearer test-metrics-key"),
                            "megano_payment_worker_up 1.0")


class PrivacyTests(SimpleTestCase):
    def test_sentry_drops_personal_data_and_signed_url(self):
        event = {"user": {"email": "person@example.com"}, "extra": {"number": "12345678"},
                 "breadcrumbs": {"values": [{"data": {"password": "secret"}}]},
                 "request": {"url": "https://example.com/payment/?token=secret", "data": {"phone": "123"},
                             "headers": {"Authorization": "secret"}, "cookies": "session", "query_string": "token=secret"}}
        cleaned = scrub_event(event, {})
        self.assertEqual(cleaned, {"request": {"url": "https://example.com/payment/"}})

    def test_s3_switch_is_explicit_and_static_stays_local(self):
        settings = {"INSTALLED_APPS": [], "MIDDLEWARE": [], "DATABASES": {"default": {}},
                    "MEDIA_ROOT": "/tmp/media", "MEDIA_URL": "/media/"}
        with patch.dict("os.environ", {"MEDIA_STORAGE": "s3", "S3_BUCKET_NAME": "megano-media", "SENTRY_DSN": ""}):
            configure_operations(settings)
        self.assertEqual(settings["STORAGES"]["default"]["BACKEND"], "storages.backends.s3.S3Storage")
        self.assertTrue(settings["STORAGES"]["default"]["OPTIONS"]["querystring_auth"])
        self.assertEqual(settings["STORAGES"]["staticfiles"]["BACKEND"], "django.contrib.staticfiles.storage.StaticFilesStorage")


class MediaCopyTests(SimpleTestCase):
    def test_copy_is_verified_repeatable_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as local, tempfile.TemporaryDirectory() as remote:
            source, target = FileSystemStorage(local), FileSystemStorage(remote)
            source.save("avatars/test.png", ContentFile(b"original-image"))
            self.assertTrue(copy_verified(source, target, "avatars/test.png"))
            self.assertFalse(copy_verified(source, target, "avatars/test.png"))
            self.assertEqual(Path(local, "avatars/test.png").read_bytes(), b"original-image")
            Path(remote, "avatars/test.png").write_bytes(b"different-image")
            with self.assertRaises(ValueError):
                copy_verified(source, target, "avatars/test.png")
            self.assertEqual(Path(remote, "avatars/test.png").read_bytes(), b"different-image")


class SetupTests(SimpleTestCase):
    def test_setup_preserves_existing_configuration_and_secrets_on_repeat(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            env = root / ".env"
            env.write_text("DJANGO_SECRET_KEY=original-key\nMETRICS_TOKEN=existing-token\n", encoding="utf-8")
            with override_settings(BASE_DIR=root):
                call_command("setup_operations", local_storage=True, stdout=io.StringIO())
                before = env.read_bytes()
                secret = (root / "infra/observability/secrets/s3.json").read_bytes()
                call_command("setup_operations", local_storage=True, stdout=io.StringIO())
            self.assertEqual(env.read_bytes(), before)
            self.assertEqual((root / "infra/observability/secrets/s3.json").read_bytes(), secret)
            self.assertEqual(dotenv_values(env)["DJANGO_SECRET_KEY"], "original-key")
            self.assertEqual((root / "infra/observability/secrets/metrics-token").read_text(), "existing-token")

    def test_local_setup_does_not_replace_cloud_endpoint(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            env = root / ".env"
            env.write_text("S3_ENDPOINT_URL=https://storage.example.com\n", encoding="utf-8")
            before = env.read_bytes()
            with override_settings(BASE_DIR=root), self.assertRaises(CommandError):
                call_command("setup_operations", local_storage=True, stdout=io.StringIO())
            self.assertEqual(env.read_bytes(), before)
            self.assertFalse((root / "infra").exists())
