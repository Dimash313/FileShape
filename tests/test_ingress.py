"""Request-size guard tests for both declared and streamed bodies."""
import asyncio
import json
import unittest

from api.ingress import UploadIngressGuard


async def read_app(scope, receive, send):
    chunks = []
    while True:
        event = await receive()
        if event["type"] == "http.disconnect":
            break
        chunks.append(event.get("body", b""))
        if not event.get("more_body", False):
            break
    data = b"".join(chunks)
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": data})


def call_guard(chunks, headers=(), path="/api/v1/convert", limit=10):
    events = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    sent = []
    async def receive():
        return events.pop(0) if events else {"type": "http.disconnect"}
    async def send(event):
        sent.append(event)
    scope = {"type": "http", "path": path, "headers": list(headers)}
    asyncio.run(UploadIngressGuard(read_app, limit, {"/api/v1/convert"})(scope, receive, send))
    return sent[0]["status"], sent[1]["body"]


class IngressTests(unittest.TestCase):
    def test_chunked_upload_under_limit(self):
        status, body = call_guard([b"1234", b"567890"])
        self.assertEqual((status, body), (200, b"1234567890"))

    def test_chunked_upload_exceeds_limit(self):
        status, body = call_guard([b"123456", b"78901"])
        self.assertEqual(status, 413)
        self.assertIn("detail", json.loads(body))

    def test_declared_size_exceeds_limit(self):
        status, _ = call_guard([b"small"], [(b"content-length", b"100")])
        self.assertEqual(status, 413)

    def test_malformed_and_negative_length(self):
        for length in (b"nope", b"-1"):
            with self.subTest(length=length):
                status, _ = call_guard([b"x"], [(b"content-length", length)])
                self.assertEqual(status, 400)

    def test_reject_duplicate_content_length_even_when_identical(self):
        cases = (
            [(b"content-length", b"5"), (b"content-length", b"5")],
            [(b"content-length", b"5"), (b"content-length", b"6")],
            [(b"Content-Length", b"5"), (b"content-length", b"5")],
        )
        for headers in cases:
            with self.subTest(headers=headers):
                status, body = call_guard([b"hello"], headers)
                self.assertEqual(status, 400)
                self.assertIn("detail", json.loads(body))

    def test_reject_length_combined_with_transfer_encoding(self):
        cases = (
            [(b"content-length", b"5"), (b"transfer-encoding", b"chunked")],
            [(b"Transfer-Encoding", b"chunked"), (b"Content-Length", b"5")],
        )
        for headers in cases:
            with self.subTest(headers=headers):
                status, _ = call_guard([b"hello"], headers)
                self.assertEqual(status, 400)

    def test_reject_noncanonical_decimal_length(self):
        for length in (b"+1", b" 1", b"1 ", b"1, 1", bytes([0xB2]), b""):
            with self.subTest(length=length):
                status, _ = call_guard([b"x"], [(b"content-length", length)])
                self.assertEqual(status, 400)

    def test_valid_chunked_body_without_declared_length_is_still_bounded(self):
        headers = [(b"Transfer-Encoding", b"chunked")]
        self.assertEqual(call_guard([b"1234", b"56"], headers, limit=6), (200, b"123456"))
        status, _ = call_guard([b"1234", b"567"], headers, limit=6)
        self.assertEqual(status, 413)

    def test_case_insensitive_single_length_is_accepted(self):
        self.assertEqual(
            call_guard([b"abc"], [(b"Content-Length", b"3")]),
            (200, b"abc"),
        )

    def test_unrelated_route_is_not_guarded(self):
        status, body = call_guard([b"12345678901"], path="/health")
        self.assertEqual((status, body), (200, b"12345678901"))


if __name__ == "__main__":
    unittest.main()
