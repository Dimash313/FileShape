"""ASGI ingress guard that counts actual bytes before multipart parsing.

A Content-Length header alone is not a reliable upload-size boundary:
clients may omit it or send chunked bodies. This wrapper enforces the cap
while Starlette consumes the stream, before UploadFile objects are parsed.
"""
from typing import Any
import re

from starlette.datastructures import Headers

class RequestTooLarge(Exception):
    pass


class UploadIngressGuard:
    def __init__(self, app: Any, max_bytes: int, paths: set[str]):
        self.app = app
        self.max_bytes = max_bytes
        self.paths = paths

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        dynamic_retry = scope.get("method") == "POST" and re.fullmatch(r"/api/v1/jobs/[^/]+/retry", path) is not None
        if scope["type"] != "http" or (path not in self.paths and not dynamic_retry):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        length = headers.get("content-length")
        if length is not None:
            try:
                declared = int(length)
            except ValueError:
                await self._reject(send, 400, "Недопустимая длина запроса")
                return
            if declared < 0:
                await self._reject(send, 400, "Недопустимая длина запроса")
                return
            if declared > self.max_bytes:
                await self._reject(send, 413, "Общий размер запроса превышает лимит")
                return

        total = 0
        response_started = False

        async def guarded_receive():
            nonlocal total
            event = await receive()
            if event["type"] == "http.request":
                total += len(event.get("body", b""))
                if total > self.max_bytes:
                    raise RequestTooLarge
            return event

        async def guarded_send(event):
            nonlocal response_started
            if event["type"] == "http.response.start":
                response_started = True
            await send(event)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except RequestTooLarge:
            if response_started:
                # The request must not be resumed after a truncated body.
                raise
            await self._reject(send, 413, "Общий размер запроса превышает лимит")

    @staticmethod
    async def _reject(send, status: int, detail: str):
        import json
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"cache-control", b"no-store"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]})
        await send({"type": "http.response.body", "body": body})
