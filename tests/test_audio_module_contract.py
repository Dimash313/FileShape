"""Audio-module contract and API-compatibility regression checks.

No FFmpeg process or uploaded file is needed for these delegation tests.
Real FFmpeg roundtrips remain covered in test_audio_tools.py.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from api import server
from services import audio_tools
from services.audio_module import AudioModulePort, ExistingAudioModule, audio_module


class AudioModuleContractTests(unittest.TestCase):
    def test_existing_adapter_satisfies_port(self):
        self.assertIsInstance(audio_module, AudioModulePort)

    def test_existing_functions_keep_their_results_and_arguments(self):
        source = Path("/private/source.wav")
        target = Path("/private/result.mp3")
        info = {"seconds": 1.5, "codec": "pcm_s16le"}
        adapter = ExistingAudioModule()
        with patch.object(audio_tools, "probe_audio", return_value=info) as probe:
            self.assertIs(adapter.probe(source), info)
            probe.assert_called_once_with(source)
        with patch.object(audio_tools, "convert_audio", return_value=info) as convert:
            self.assertIs(adapter.convert(source, target, "mp3"), info)
            convert.assert_called_once_with(source, target, "mp3")

    def test_adapter_propagates_processing_failures(self):
        with patch.object(audio_tools, "convert_audio", side_effect=ValueError("invalid media")):
            with self.assertRaisesRegex(ValueError, "invalid media"):
                audio_module.convert(Path("/private/input"), Path("/private/output.mp3"), "mp3")

    def test_api_info_delegates_through_audio_module(self):
        source = Path("/private/input.wav")
        info = {"seconds": 4.0, "codec": "pcm_s16le"}
        with patch.object(server, "audio_module") as adapter:
            adapter.probe.return_value = info
            self.assertEqual(server._info_action(source, "audio:info"), {"info": info})
            adapter.probe.assert_called_once_with(source)
            adapter.convert.assert_not_called()
            self.assertIsNone(server._info_action(source, "not:an:action"))

    def test_api_conversion_preserves_name_format_and_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.wav"
            output_dir = Path(directory)
            with patch.object(server, "audio_module") as adapter:
                result = server._transform(source, output_dir, "audio:ogg", "")
                self.assertEqual(result, output_dir / "converted.ogg")
                adapter.convert.assert_called_once_with(
                    source, output_dir / "converted.ogg", "ogg",
                )
                adapter.probe.assert_not_called()

    def test_api_conversion_propagates_failure_without_fake_result(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.wav"
            with patch.object(server, "audio_module") as adapter:
                adapter.convert.side_effect = ValueError("conversion failed")
                with self.assertRaisesRegex(ValueError, "conversion failed"):
                    server._transform(source, Path(directory), "audio:mp3", "")

    def test_public_audio_action_set_is_unchanged(self):
        from api.conversion_catalog import SUPPORTED
        self.assertEqual(
            SUPPORTED["audio"],
            {"audio:mp3", "audio:ogg", "audio:wav", "audio:info"},
        )


if __name__ == "__main__":
    unittest.main()
