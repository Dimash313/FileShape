"""Bounded image conversion and optimization for private temporary files.

Image-specific implementation. All paths are caller-controlled temporary
paths; authentication, quotas, cleanup and upload validation belong to
application/workspace layers.
"""
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import stat
import tempfile
from typing import BinaryIO
import warnings

from PIL import Image, ImageOps

MAX_IMAGE_PIXELS = 35_000_000

IMAGE_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "PDF": ".pdf"}
SUPPORTED_IMAGE_INPUT_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


def _validate_image_input_header(image: Image.Image) -> None:
    """Reject hidden image parsers and silent first-frame conversion.

    Source extensions are not trusted format evidence. An animated APNG or
    WebP would otherwise produce only one frame in PDF/JPEG conversions.
    """
    if image.format not in SUPPORTED_IMAGE_INPUT_FORMATS:
        raise ValueError("Unsupported image input format")
    if getattr(image, "n_frames", 1) != 1:
        raise ValueError("Multi-frame images are not supported")


@contextmanager
def _open_regular_image_source(source: Path):
    """Pin a regular source inode without following final symlinks.

    Nonblocking open prevents FIFOs from hanging before fstat checks. An
    already-open descriptor remains bound to its original inode even if the
    pathname is later replaced. This does not prevent in-place mutation.
    """
    if source.is_symlink():
        raise ValueError("Поддерживаются только обычные файлы изображений")
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        descriptor = os.open(source, flags)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENXIO):
            raise ValueError("Поддерживаются только обычные файлы изображений") from None
        raise
    try:
        stream = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Поддерживаются только обычные файлы изображений")
        yield stream


@contextmanager
def _atomic_image_output(target: Path):
    """Publish only completely encoded output, preserving a previous result.

    A same-directory private stage keeps writes within the caller's workspace,
    allows an atomic final rename, and avoids exposing partial image files.
    """
    fd, stage_name = tempfile.mkstemp(
        prefix=".fileshape_image_", suffix=".tmp", dir=target.parent,
    )
    os.close(fd)
    stage = Path(stage_name)
    try:
        yield stage
        os.replace(stage, target)
    finally:
        stage.unlink(missing_ok=True)


def _open_image(source: Path | BinaryIO) -> Image.Image:
    """Decode a source Path or a caller-pinned stream without closing it."""
    if isinstance(source, (str, os.PathLike)):
        with _open_regular_image_source(Path(source)) as stream:
            return _open_image(stream)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(source) as original:
            _validate_image_input_header(original)
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
                try:
                    white = Image.new("RGB", rgba.size, "white")
                    white.paste(rgba, mask=rgba.getchannel("A"))
                finally:
                    rgba.close()
                image.close()
                image = white
            else:
                rgb = image.convert("RGB")
                image.close()
                image = rgb
        elif fmt == "PNG" and image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            converted = image.convert("RGBA")
            image.close()
            image = converted

        # All formats are explicit: the staging .tmp suffix is not used to
        # guess the encoder, nor is it ever exposed as a completed result.
        with _atomic_image_output(target) as staged:
            if fmt == "JPEG":
                image.save(staged, format="JPEG", quality=88, optimize=True)
            elif fmt == "PDF":
                image.save(staged, format="PDF", resolution=96.0)
            elif fmt == "WEBP":
                image.save(staged, format="WEBP", quality=85, method=4)
            else:
                image.save(staged, format="PNG", optimize=True)
    finally:
        image.close()


def compress_image(source: Path, target: Path) -> None:
    """Save as WebP at quality 72; size reduction is not guaranteed."""
    image = _open_image(source)
    try:
        with _atomic_image_output(target) as staged:
            image.save(staged, format="WEBP", quality=72, method=4)
    finally:
        image.close()
