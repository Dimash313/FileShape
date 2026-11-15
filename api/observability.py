"""Privacy-preserving ASGI request tracing.

Only fixed route categories, status and duration are logged.
Never log Telegram initData, file names, file contents or user identifiers.
"""
import logging
import re
import secrets
import time

logger = logging.getLogger("fileshape.requests")

# Category keys are static; never interpolate a URL, username or job ID.
ROUTES = {
    "/health": "health",
    "/ready": "ready",
    "/api/v1/session": "session",
    "/api/v1/convert": "convert",
    "/api/v1/images/pdf": "images_pdf",
    "/api/v1/capabilities": "capabilities",
    "/api/v1/queue": "queue",
    "/api/v1/usage": "usage",
    "/api/v1/jobs": "jobs_submit",
    "/api/v1/pdf/merge": "pdf_merge",
    "/api/v1/zip/create": "zip_create",
    "/internal/v1/access/check": "internal_access",
    "/internal/v1/operations/usage": "internal_usage",
    "/internal/v1/operations/reserve": "internal_reserve",
    "/internal/v1/operations/settle": "internal_settle",
    "/internal/v1/campaigns/join": "internal_campaign_join",
}

# Existing jobs use 32-character, server-generated URL-safe IDs. Recognize
# only those shapes: arbitrary extra path segments must stay anonymous.
_JOB_PATH = re.compile(r"/api/v1/jobs/[A-Za-z0-9_-]{32}(?:/(result|cancel|retry))?")
_JOB_LABELS = {
    None: "job_status",
    "result": "job_result",
    "cancel": "job_cancel",
    "retry": "job_retry",
}


def route_label(path: object) -> str:
    """Classify a *shape* into a fixed label without exposing user input."""
    if not isinstance(path, str):
        return "other"
    fixed = ROUTES.get(path)
    if fixed is not None:
        return fixed
    matched = _JOB_PATH.fullmatch(path)
    return _JOB_LABELS[matched.group(1)] if matched else "other"


class RequestTrace:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        trace_id = secrets.token_hex(8)
        route = route_label(scope.get("path"))
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
            logger.error("request_failed id=%s route=%s", trace_id, route)
            raise
        finally:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            logger.info(
                "request id=%s route=%s status=%d duration_ms=%d",
                trace_id, route, status, elapsed_ms,
            )
