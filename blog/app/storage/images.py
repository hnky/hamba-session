"""Bounded raster-image validation and normalization for author uploads."""

from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def normalize_upload(content: bytes) -> tuple[bytes, str]:
    """Decode real image bytes, strip metadata, and store a safe JPEG."""
    if not content:
        raise ValueError("The uploaded image is empty")
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 8 MB limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format not in ALLOWED_FORMATS:
                    raise ValueError("Choose a JPEG, PNG, or WebP image")
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image exceeds the 20 megapixel limit")
                image.verify()
            with Image.open(BytesIO(content)) as image:
                oriented = ImageOps.exif_transpose(image)
                rgba = oriented.convert("RGBA")
                flattened = Image.new("RGB", rgba.size, "white")
                flattened.paste(rgba, mask=rgba.getchannel("A"))
                output = BytesIO()
                flattened.save(output, format="JPEG", quality=90)
        result = output.getvalue()
        if len(result) > MAX_IMAGE_BYTES:
            raise ValueError("Processed image exceeds 8 MB; choose a smaller image")
        return result, "image/jpeg"
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("The file is not a valid JPEG, PNG, or WebP image") from exc