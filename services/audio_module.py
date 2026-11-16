"""Typed audio-processing boundary for FileShape's modular monolith.

This is an in-process adapter over the existing, bounded FFmpeg functions.
It does NOT replace authorization, quota checks, upload validation, sandboxing,
subprocess resource limits or temporary-file cleanup at the application edge.
"""
from pathlib import Path
from typing import Protocol, TypedDict, runtime_checkable

from services import audio_tools


class AudioInfo(TypedDict):
    seconds: float
    codec: str


@runtime_checkable
class AudioModulePort(Protocol):
    """Format-specific operations; independent of Telegram, API and billing."""

    def probe(self, source: Path) -> AudioInfo: ...

    def convert(self, source: Path, target: Path, output_format: str) -> AudioInfo: ...


class ExistingAudioModule:
    """Compatibility adapter: preserve legacy conversions and return shapes."""

    def probe(self, source: Path) -> AudioInfo:
        return audio_tools.probe_audio(source)

    def convert(self, source: Path, target: Path, output_format: str) -> AudioInfo:
        return audio_tools.convert_audio(source, target, output_format)


audio_module: AudioModulePort = ExistingAudioModule()
