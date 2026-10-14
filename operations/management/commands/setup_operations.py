import json
import os
import secrets
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from dotenv import dotenv_values


class Command(BaseCommand):
    help = "Создать локальные секреты мониторинга; существующие значения .env сохраняются"

    def add_arguments(self, parser):
        parser.add_argument("--local-storage", action="store_true")

    def handle(self, *args, **options):
        env_path = settings.BASE_DIR / ".env"
        existing = {**dotenv_values(env_path), **os.environ}
        additions = {}
        if options["local_storage"] and existing.get("S3_ENDPOINT_URL") not in (None, "", "http://127.0.0.1:8333"):
            raise CommandError("Облачное хранилище уже задано; не заменяем его локальным")

        def value(key, default):
            result = existing.get(key) or default
            if not existing.get(key):
                additions[key] = result
            return result

        token = value("METRICS_TOKEN", secrets.token_urlsafe(32))
        directory = settings.BASE_DIR / "infra" / "observability" / "secrets"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "metrics-token").write_text(token, encoding="utf-8")
        os.chmod(directory / "metrics-token", 0o644)  # Read by the container; parent directory is private.
        os.chmod(directory, 0o700)
        compose_env = directory.parent / ".env"
        previous = dotenv_values(compose_env) if compose_env.exists() else {}
        password = previous.get("GRAFANA_ADMIN_PASSWORD") or secrets.token_urlsafe(24)
        compose_env.write_text("GRAFANA_ADMIN_PASSWORD=" + password + "\n", encoding="utf-8")
        os.chmod(compose_env, 0o600)
        if options["local_storage"]:
            endpoint = existing.get("S3_ENDPOINT_URL") or "http://127.0.0.1:8333"
            if endpoint != "http://127.0.0.1:8333":
                raise CommandError("Облачное хранилище уже задано; не заменяем его локальным")
            access = value("S3_ACCESS_KEY_ID", secrets.token_hex(12))
            secret = value("S3_SECRET_ACCESS_KEY", secrets.token_urlsafe(32))
            value("S3_BUCKET_NAME", "megano-media")
            value("S3_ENDPOINT_URL", endpoint)
            value("S3_REGION_NAME", "us-east-1")
            identity = {"identities": [{"name": "megano", "credentials": [
                {"accessKey": access, "secretKey": secret}],
                "actions": ["Read:megano-media", "Write:megano-media", "List:megano-media", "Admin:megano-media"]}]}
            # Use the configured bucket, preserving an existing local installation.
            bucket = existing.get("S3_BUCKET_NAME") or additions["S3_BUCKET_NAME"]
            identity["identities"][0]["actions"] = [f"{action}:{bucket}" for action in ("Read", "Write", "List", "Admin")]
            (directory / "s3.json").write_text(json.dumps(identity), encoding="utf-8")
            os.chmod(directory / "s3.json", 0o644)
        with env_path.open("a", encoding="utf-8") as file:
            if additions:
                file.write("\n# Operations integration\n")
                for key, item in additions.items():
                    file.write(f"{key}={item}\n")
        os.chmod(env_path, 0o600)
        self.stdout.write("Настройки подготовлены. Секреты сохранены локально и не выводятся.")
        self.stdout.write("После копирования и проверки media переключите MEDIA_STORAGE=s3 и перезапустите сайт.")
