"""Versioned, read-only HTTP conversion catalog for future FileShape clients.

This is descriptive metadata for the existing single-file /api/v1/convert
action allowlist, not a permission grant, content-type validation, a plugin
registry, runtime health check, or a promise about bot/mobile support.
"""
from __future__ import annotations

from api.conversion_catalog import IMAGE_EXTENSIONS, SUPPORTED
from services.audio_tools import AUDIO_EXTENSIONS
from services.image_bundle import MIN_IMAGES, MAX_IMAGES
from services.pdf_tools import MAX_MERGE_FILES
from services.archive_tools import MAX_BUNDLE_FILES


# Keep routing metadata separate from which actions are actually enabled.
# An unknown new kind must be reviewed explicitly, never advertised by guess.
_INPUT_SUFFIXES: dict[str, tuple[str, ...]] = {
    "archive": (".zip",),
    "audio": tuple(sorted(AUDIO_EXTENSIONS)),
    "docx": (".docx",),
    "image": tuple(sorted(IMAGE_EXTENSIONS)),
    "pdf": (".pdf",),
    "txt": (".txt",),
}


def build_http_capabilities() -> dict:
    """Return a fresh JSON-serializable snapshot of the real action allowlist.

    This contract describes only current HTTP routes, not Telegram or mobile.
    No user identifiers, token, account, payment state or internal artifact
    references are present in the response.
    """
    if set(SUPPORTED) != set(_INPUT_SUFFIXES):
        raise RuntimeError("HTTP capability kinds need an explicit routing review")
    return {
        "schema_version": 1,
        "surface": "http",
        "route": "/api/v1/convert",
        "classification": "filename_suffix_for_routing_only",
        "operations": [
            {
                "kind": kind,
                "input_extensions": list(_INPUT_SUFFIXES[kind]),
                "actions": sorted(SUPPORTED[kind]),
            }
            for kind in sorted(SUPPORTED)
        ],
        # Explicitly separate multi-file routes from single-file action codes.
        # ZIP extraction is not available over HTTP yet.
        "batch_operations": [
            {
                "route": "/api/v1/images/pdf",
                "method": "POST",
                "input_kind": "image",
                "input_extensions": list(_INPUT_SUFFIXES["image"]),
                "min_files": MIN_IMAGES,
                "max_files": MAX_IMAGES,
                "output_extension": ".pdf",
            },
            {
                "route": "/api/v1/pdf/merge",
                "method": "POST",
                "input_kind": "pdf",
                "input_extensions": [".pdf"],
                "min_files": 2,
                "max_files": MAX_MERGE_FILES,
                "output_extension": ".pdf",
            },
            {
                "route": "/api/v1/zip/create",
                "method": "POST",
                "input_kind": "any_file",
                # Empty extensions means all file suffixes are accepted.
                "input_extensions": [],
                "accept_any_file_type": True,
                "min_files": 2,
                "max_files": MAX_BUNDLE_FILES,
                "output_extension": ".zip",
            },
        ],
    }
