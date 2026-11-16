"""Bounded multi-image PDF builder for temporary server-side files."""
from contextlib import ExitStack
from pathlib import Path
import os
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

    # Hold all descriptors open across header preflight and decode. Checking
    # each path twice is insufficient: os.replace can swap regular files
    # without ever introducing a symlink.
    with ExitStack() as inputs:
        streams = []
        total_bytes = 0
        for source in sources:
            stream = inputs.enter_context(image_tools._open_regular_image_source(source))
            total_bytes += os.fstat(stream.fileno()).st_size
            if total_bytes > MAX_BUNDLE_BYTES:
                raise ValueError("Общий размер фотографий превышает 20 МБ")
            streams.append(stream)

        # Preflight every header on its pinned descriptor, before any pixel
        # decoder runs. The same descriptors are reused below.
        header_pixels = 0
        for stream in streams:
            stream.seek(0)
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(stream) as probe:
                    image_tools._validate_image_input_header(probe)
                    pixels = probe.width * probe.height
                    if pixels > image_tools.MAX_IMAGE_PIXELS:
                        raise ValueError("Image dimensions exceed the limit")
                    header_pixels += pixels
                    if header_pixels > MAX_BUNDLE_PIXELS:
                        raise ValueError("Слишком большое суммарное разрешение фотографий")

        with ExitStack() as stack:
            pages: list[Image.Image] = []
            total_pixels = 0
            actual_bytes = 0
            for stream in streams:
                # An inode may still be modified in place; recheck size and
                # decoded pixels before page-buffer conversion.
                actual_bytes += os.fstat(stream.fileno()).st_size
                if actual_bytes > MAX_BUNDLE_BYTES:
                    raise ValueError("Общий размер фотографий превышает 20 МБ")
                stream.seek(0)
                # Retain only the completed RGB pages until PDF encoding.
                # The decoded source and temporary RGBA copy can be released
                # before decoding the next member. This avoids accumulating
                # redundant high-pixel image buffers across the full batch.
                with ExitStack() as transient:
                    image = _open_image(stream)
                    transient.callback(image.close)
                    total_pixels += image.width * image.height
                    if total_pixels > MAX_BUNDLE_PIXELS:
                        raise ValueError("Слишком большое суммарное разрешение фотографий")
                    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                        rgba = image.convert("RGBA")
                        transient.callback(rgba.close)
                        converted = Image.new("RGB", image.size, "white")
                        # Register before paste: a failure during compositing
                        # must also free the newly allocated RGB canvas.
                        stack.callback(converted.close)
                        converted.paste(rgba, mask=rgba.getchannel("A"))
                    else:
                        converted = image.convert("RGB")
                        stack.callback(converted.close)
                    pages.append(converted)
            # Only publish a complete PDF, preserving an existing result if
            # either the encoder or final publication fails.
            with _atomic_image_output(target) as staged:
                pages[0].save(
                    staged,
                    format="PDF",
                    save_all=True,
                    append_images=pages[1:],
                    resolution=96.0,
                )
    return len(pages)
