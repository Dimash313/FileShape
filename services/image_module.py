"""Typed, in-process boundary for FileShape image transformations.

Actual parsers and conversion presets remain in services.image_tools.
Upload validation, authorization, quota, workspaces and result publication
remain in the calling application layers.
"""
from pathlib import Path
from typing import Protocol, runtime_checkable

from services import image_tools, image_bundle


@runtime_checkable
class ImageModulePort(Protocol):
    """Keep format conversion independent of API, bot and billing code."""

    def convert(self, source: Path, target: Path, fmt: str) -> None: ...

    def compress(self, source: Path, target: Path) -> None: ...

    def bundle_as_pdf(self, sources: list[Path], target: Path) -> int: ...


class ExistingImageModule:
    """Compatibility adapter preserving existing image conversion behavior."""

    def convert(self, source: Path, target: Path, fmt: str) -> None:
        return image_tools.convert_image(source, target, fmt)

    def compress(self, source: Path, target: Path) -> None:
        return image_tools.compress_image(source, target)

    def bundle_as_pdf(self, sources: list[Path], target: Path) -> int:
        return image_bundle.images_to_pdf(sources, target)


image_module: ImageModulePort = ExistingImageModule()
