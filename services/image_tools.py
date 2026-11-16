"""Bounded image conversion and optimization for private temporary files.

Image-specific implementation. All paths are caller-controlled temporary
paths; authentication, quotas, cleanup and upload validation belong to
application/workspace layers.
"""
from pathlib import Path
import warnings

from PIL import Image, ImageOps

MAX_IMAGE_PIXELS = 35_000_000

IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "PDF": ".pdf"}
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def _open_image(source: Path) -> Image.Image:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(source) as original:
            if original.width * original.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image dimensions exceed the limit")
            image = ImageOps.exif_transpose(original)
            image.load()
            return image


def convert_image(source: Path, target: Path, fmt: str) -> None:
    fmt = fmt.upper()
    if fmt not in IMAGE_FORMATS:
        raise ValueError("Unsupported image format")
    image = _open_image(source)
    try:
        if fmt in ("JPEG", "PDF"):
            # Transparent pixels turn white, not black.
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                white = Image.new("RGB", rgba.size, "white")
                white.paste(rgba, mask=rgba.getchannel("A"))
                image.close()
                image = white
            else:
                rgb = image.convert("RGB")
                image.close()
                image = rgb
            if fmt == "JPEG":
                image.save(target, format="JPEG", quality=88, optimize=True)
            else:
                image.save(target, format="PDF", resolution=96.0)
        elif fmt == "WEBP":
            image.save(target, format="WEBP", quality=85, method=4)
        else:
            if image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                image = image.convert("RGBA")
            image.save(target, format="PNG", optimize=True)
    finally:
        image.close()


def compress_image(source: Path, target: Path) -> None:
    """Save as WebP at quality 72; size reduction is not guaranteed."""
    image = _open_image(source)
    try:
        image.save(target, format="WEBP", quality=72, method=4)
    finally:
        image.close()
