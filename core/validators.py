from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError


def validate_image(upload):
    """Check size and contents, including uploads made outside the admin."""
    if upload.size > 2 * 1024 * 1024:
        raise ValidationError("Размер изображения не должен превышать 2 МиБ.")
    position = upload.tell()
    try:
        with Image.open(upload) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValidationError("Загрузите корректное изображение.") from error
    finally:
        upload.seek(position)
