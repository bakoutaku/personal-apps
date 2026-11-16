"""本机安全中间件（ARCHITECTURE §4）。

1. Host 头必须是 127.0.0.1:<port> 或 localhost:<port>（防 DNS rebinding）→ 否则 421
2. 带 Origin 时必须在允许列表内，`null` 一律拒绝 → 否则 403
3. Sec-Fetch-Site 为 cross-site 时拒绝
4. 写请求必须带 X-Wardrobe-Client（自定义头会触发 CORS 预检，跨站页面无法发出）→ 否则 403
"""

import json
import re

from starlette.types import ASGIApp, Receive, Scope, Send

from .config import Settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CLIENT_HEADER = "x-wardrobe-client"
CLIENT_RE = re.compile(r"^[a-z0-9][a-z0-9:._-]{0,63}$")
PRIVILEGED_CLIENTS = frozenset({"web-ui", "cli"})
# 所有响应都带的通用安全头（防点击劫持、MIME 嗅探、外泄 Referer）
SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
]


def is_privileged(actor: str) -> bool:
    """白名单：只有 web-ui / cli 可修改已核实记录；其他一切值（含未知、拼错）都受限。"""
    return actor in PRIVILEGED_CLIENTS


class LocalOnlyMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.allowed_hosts = settings.allowed_hosts
        self.allowed_origins = settings.allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        method = scope["method"]

        host = headers.get("host", "")
        if host not in self.allowed_hosts:
            await _reject(send, 421, "MISDIRECTED_HOST", f"不接受的 Host: {host!r}")
            return

        origin = headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            await _reject(send, 403, "ORIGIN_FORBIDDEN", f"不接受的来源: {origin!r}")
            return

        if headers.get("sec-fetch-site") == "cross-site":
            await _reject(send, 403, "ORIGIN_FORBIDDEN", "拒绝跨站请求")
            return

        client = headers.get(CLIENT_HEADER, "").strip().lower()
        if method not in SAFE_METHODS:
            if not client:
                await _reject(
                    send, 403, "CLIENT_HEADER_REQUIRED", "写请求必须带 X-Wardrobe-Client 头（如 web-ui、cli、ai:codex）"
                )
                return
            if not CLIENT_RE.match(client):
                await _reject(send, 403, "CLIENT_HEADER_INVALID", "X-Wardrobe-Client 只能包含小写字母、数字和 :._-")
                return

        scope.setdefault("state", {})["actor"] = client or "anonymous"

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], *SECURITY_HEADERS]
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def _reject(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message, "details": []}}, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                *SECURITY_HEADERS,
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
