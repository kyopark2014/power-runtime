"""HTTP security response headers for the Web UI / API.

Applied via Starlette middleware so every response (including SPA and SSE)
gets a baseline set. CloudFront Managed-SecurityHeadersPolicy layers HSTS and
related headers at the edge; CSP locks down same-origin UI/API traffic.
"""

from __future__ import annotations

import json
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


def _s3_connect_src_hosts() -> str:
    """Allow browser→S3 presigned PUT/GET used by Load-files / RAG uploads.

    Without these, CSP blocks ``fetch(presignedUrl)`` as ``Failed to fetch``.
    Host wildcards only match one DNS label, so regional path-style and
    virtual-hosted forms are listed explicitly from config.json.
    """
    region = "us-west-2"
    bucket = ""
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        region = (cfg.get("region") or region).strip() or region
        bucket = (cfg.get("s3_bucket") or "").strip()
    except Exception:
        logger.debug("CSP S3 hosts: using defaults (config.json unread)", exc_info=True)

    hosts = [
        f"https://s3.{region}.amazonaws.com",
        f"https://*.s3.{region}.amazonaws.com",
        "https://*.s3.amazonaws.com",
        "https://s3.amazonaws.com",
    ]
    if bucket:
        hosts.append(f"https://{bucket}.s3.{region}.amazonaws.com")
        hosts.append(f"https://{bucket}.s3.amazonaws.com")
    return " ".join(hosts)


# connect-src includes S3 so Load-files / RAG can PUT directly to presigned URLs.
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "font-src 'self' data:; "
    f"connect-src 'self' {_s3_connect_src_hosts()}; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)

_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": _CONTENT_SECURITY_POLICY,
}

_HSTS = "max-age=31536000; includeSubDomains"


def _viewer_is_https(request: Request) -> bool:
    proto = (
        request.headers.get("cloudfront-forwarded-proto")
        or request.headers.get("x-forwarded-proto")
        or request.url.scheme
        or ""
    ).lower()
    return proto == "https"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers; HSTS only for HTTPS viewers."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in _BASE_HEADERS.items():
            response.headers.setdefault(name, value)
        if _viewer_is_https(request):
            response.headers.setdefault("Strict-Transport-Security", _HSTS)
        return response
