"""Legacy compatibility exports for image and PDF tools.

New code must import services.image_tools / services.pdf_tools directly or
use their typed modules. This facade preserves existing public Python
imports and contains no format-specific implementation.
"""
from services.image_tools import (  # noqa: F401
    IMAGE_FORMATS,
    MAX_IMAGE_PIXELS,
    _open_image,
    compress_image,
    convert_image,
)

# Legacy public import paths. New PDF code belongs in services.pdf_tools,
# not here; preserve callers that import PDF functions from file_tools.
from services.pdf_tools import (  # noqa: E402
    MAX_MERGE_FILES,
    MAX_PDF_PAGES,
    MAX_SELECTED_PAGES,
    _reader,
    extract_pdf_pages,
    merge_pdfs,
    parse_page_selection,
    pdf_page_count,
    remove_pdf_pages,
    rotate_pdf,
)
