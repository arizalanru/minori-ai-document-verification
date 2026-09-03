from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.core.errors import DomainError


def inspect_image(content, max_pixels):
    if not content:
        raise DomainError("EMPTY_FILE", "File kosong")
    try:
        with Image.open(BytesIO(content)) as im:
            if im.format not in ("JPEG", "PNG"):
                raise DomainError("UNSUPPORTED_FILE", "P0 hanya JPEG/PNG", 415)
            if im.width * im.height > max_pixels:
                raise DomainError("IMAGE_TOO_LARGE", "Dimensi terlalu besar", 413)
            image_format = im.format
            im.verify()
        with Image.open(BytesIO(content)) as im:
            im.load()
    except DomainError:
        raise
    except Image.DecompressionBombError:
        raise DomainError("IMAGE_TOO_LARGE", "Dimensi terlalu besar", 413) from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise DomainError("INVALID_IMAGE", "File tidak dapat dibaca") from None
    return ".jpg" if image_format == "JPEG" else ".png"
