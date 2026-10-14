from pathlib import Path
from django.conf import settings
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from operations.media import copy_verified, digest


class Command(BaseCommand):
    help = "Копировать media в S3 с проверкой SHA256, сохраняя локальные файлы и имена в базе"

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true")
        mode.add_argument("--verify", action="store_true")

    def handle(self, *args, **options):
        if "object_media" not in settings.STORAGES:
            raise CommandError("Сначала задайте S3_BUCKET_NAME и параметры подключения в .env")
        root = Path(settings.MEDIA_ROOT).resolve()
        source, target = storages["local_media"], storages["object_media"]
        count = copied = 0
        try:
            for path in sorted(root.rglob("*")):
                if path.is_symlink():
                    raise CommandError("Символические ссылки в media не поддерживаются")
                if not path.is_file():
                    continue
                name = path.relative_to(root).as_posix()
                count += 1
                if options["apply"]:
                    copied += copy_verified(source, target, name)
                elif options["verify"]:
                    if not target.exists(name) or digest(source, name) != digest(target, name):
                        raise CommandError("Не совпадает файл: " + name)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        if not options["apply"] and not options["verify"]:
            self.stdout.write(f"План: {count} файлов. Для копирования добавьте --apply.")
        else:
            self.stdout.write(f"Проверено: {count}; скопировано: {copied}. Локальные файлы сохранены.")
