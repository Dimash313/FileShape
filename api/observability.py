"""Privacy-preserving ASGI request tracing.

Only fixed route categories, status and duration are logged.
Never log Telegram initData, file names, file contents or user identifiers.
"""
import logging
import secrets
import time

logger = logging.getLogger("fileshape.requests")

ROUTES = {
    "/health": "health",
    "/ready": "ready",
    "/api/v1/session": "session",
    "/api/v1/convert": "convert",
    "/api/v1/images/pdf": "images_pdf",
}


class RequestTrace:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        trace_id = secrets.token_hex(8)
        route = ROUTES.get(scope.get("path"), "other")
        started = time.monotonic()
        status = 500

        async def traced_send(event):
            nonlocal status
            if event["type"] == "http.response.start":
                status = event["status"]
                headers = list(event.get("headers", []))
                headers.append((b"x-request-id", trace_id.encode("ascii")))
                event = {**event, "headers": headers}
            await send(event)

        try:
            await self.app(scope, receive, traced_send)
        except Exception:
            logger.exception("request_failed id=%s route=%s", trace_id, route)
            raise
        finally:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            logger.info(
                "request id=%s route=%s status=%d duration_ms=%d",
                trace_id, route, status, elapsed_ms,
            )
