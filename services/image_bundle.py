"""Bounded multi-image PDF builder for temporary server-side files."""
from contextlib import ExitStack
from pathlib import Path
import stat
import warnings

from PIL import Image

from services import image_tools
from services.image_tools import _atomic_image_output, _open_image

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

    # Reject unexpected source types and oversized aggregate input before
    # opening any image decoder. Callers supply private workspace paths, but
    # a FIFO/symlink is never a valid source for this file-based operation.
    total_bytes = 0
    for source in sources:
        if source.is_symlink() or not stat.S_ISREG(source.stat().st_mode):
            raise ValueError("Поддерживаются только обычные файлы изображений")
        total_bytes += source.stat().st_size
        if total_bytes > MAX_BUNDLE_BYTES:
            raise ValueError("Общий размер фотографий превышает 20 МБ")

    # A header-only pass lets us reject oversized *batches* without decoding
    # the first large member or allocating RGB/RGBA page buffers. The existing
    # single-image pixel cap is kept as well.
    header_pixels = 0
    for source in sources:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as probe:
                pixels = probe.width * probe.height
                if pixels > image_tools.MAX_IMAGE_PIXELS:
                    raise ValueError("Image dimensions exceed the limit")
                header_pixels += pixels
                if header_pixels > MAX_BUNDLE_PIXELS:
                    raise ValueError("Слишком большое суммарное разрешение фотографий")

    with ExitStack() as stack:
        pages: list[Image.Image] = []
        total_pixels = 0
        for source in sources:
            # Source bytes and dimensions may change after the header pass.
            # Enforce both cumulative limits again before conversion.
            if source.is_symlink() or not stat.S_ISREG(source.stat().st_mode):
                raise ValueError("Поддерживаются только обычные файлы изображений")
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
        # Only publish a complete PDF; preserve an existing result if the
        # encoder or filesystem fails after writing a partial stage file.
        # This reuses the same image-domain output policy as conversions.
        with _atomic_image_output(target) as staged:
            pages[0].save(
                staged,
                format="PDF",
                save_all=True,
                append_images=pages[1:],
                resolution=96.0,
            )
    return len(pages)
