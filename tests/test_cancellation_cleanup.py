"""Cancelled requests must remove partial uploads and release API slots."""
import asyncio
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import UploadFile
from PIL import Image

from api.server import convert, multi_image_pdf, slots


def image_upload(name="picture.png"):
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, "PNG")
    return UploadFile(file=BytesIO(buffer.getvalue()), filename=name)


class CancellationCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def exercise_cancellation(self, handler):
        entered = asyncio.Event()
        paths = []
        original = tempfile.TemporaryDirectory

        def tracked_temp(*args, **kwargs):
            work = original(*args, **kwargs)
            paths.append(Path(work.name))
            return work

        async def hanging_worker(payload):
            entered.set()
            await asyncio.Event().wait()

        with patch("api.server.tempfile.TemporaryDirectory", side_effect=tracked_temp):
            with patch("api.server.run_worker", side_effect=hanging_worker):
                task = asyncio.create_task(handler())
                try:
                    await asyncio.wait_for(entered.wait(), timeout=4)
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task

        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists(), "Cancelled request left temporary files")
        self.assertEqual(slots._value, 3)

    async def test_cancel_single_conversion(self):
        async def handler():
            await convert(
                upload=image_upload(),
                action="img:JPEG",
                pages="",
                user_id=112233,
            )
        await self.exercise_cancellation(handler)

    async def test_cancel_multi_image_conversion(self):
        async def handler():
            await multi_image_pdf(
                uploads=[image_upload("a.png"), image_upload("b.png")],
                user_id=112234,
            )
        await self.exercise_cancellation(handler)


if __name__ == "__main__":
    unittest.main()
