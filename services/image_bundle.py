"""Bounded multi-image PDF builder for temporary server-side files."""
from contextlib import ExitStack
from pathlib import Path

from PIL import Image

from services.image_tools import _open_image

MIN_IMAGES = 2
MAX_IMAGES = 8
MAX_BUNDLE_BYTES = 20 * 1024 * 1024
MAX_BUNDLE_PIXELS = 22_000_000


def images_to_pdf(sources: list[Path], target: Path) -> int:
    """Combine 2–8 JPEG/PNG/WebP images in user-provided order.

    Limits total decoded pixel count before materializing all pages.
    Flatten transparency against white and apply EXIF orientation.
    """
    if not MIN_IMAGES <= len(sources) <= MAX_IMAGES:
        raise ValueError("Нужно от 2 до 8 изображений")
    if sum(source.stat().st_size for source in sources) > MAX_BUNDLE_BYTES:
        raise ValueError("Общий размер фотографий превышает 20 МБ")

    with ExitStack() as stack:
        pages: list[Image.Image] = []
        total_pixels = 0
        for source in sources:
            image = _open_image(source)
            stack.callback(image.close)
            total_pixels += image.width * image.height
            if total_pixels > MAX_BUNDLE_PIXELS:
                raise ValueError("Слишком большое суммарное разрешение фотографий")
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                stack.callback(rgba.close)
                converted = Image.new("RGB", image.size, "white")
                converted.paste(rgba, mask=rgba.getchannel("A"))
            else:
                converted = image.convert("RGB")
            stack.callback(converted.close)
            pages.append(converted)
        pages[0].save(
            target,
            format="PDF",
            save_all=True,
            append_images=pages[1:],
            resolution=96.0,
        )
    return len(pages)
