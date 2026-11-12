"""Safe local transformations for user-supplied files."""
from pathlib import Path
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter

IMAGE_FORMATS = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}


def convert_image(source: Path, target: Path, fmt: str) -> None:
    fmt = fmt.upper()
    if fmt not in IMAGE_FORMATS:
        raise ValueError('Unsupported image format')
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original)
        image.load()
        if image.width * image.height > 40_000_000:
            raise ValueError('Image is too large')
        if fmt == 'JPEG':
            image = image.convert('RGB')
        image.save(target, format=fmt, optimize=True)


def split_pdf(source: Path, target: Path) -> int:
    reader = PdfReader(str(source), strict=True)
    if reader.is_encrypted:
        raise ValueError('Password-protected PDFs are not supported')
    if not reader.pages:
        raise ValueError('PDF contains no pages')
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    with target.open('wb') as stream:
        writer.write(stream)
    return len(reader.pages)
