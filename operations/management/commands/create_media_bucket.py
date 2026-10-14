from django.conf import settings
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from botocore.exceptions import ClientError


class Command(BaseCommand):
    help = "Создать bucket локального S3; существующий bucket и его файлы сохраняются"

    def handle(self, *args, **options):
        if "object_media" not in settings.STORAGES:
            raise CommandError("S3_BUCKET_NAME не задан")
        storage = storages["object_media"]
        client = storage.connection.meta.client
        try:
            client.head_bucket(Bucket=storage.bucket_name)
        except ClientError as exc:
            if str(exc.response["Error"]["Code"]) not in ("404", "NoSuchBucket", "NotFound"):
                raise CommandError("Нет доступа к bucket; проверьте настройки S3") from exc
            kwargs = {"Bucket": storage.bucket_name}
            if storage.region_name != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": storage.region_name}
            client.create_bucket(**kwargs)
        self.stdout.write("Bucket доступен.")
