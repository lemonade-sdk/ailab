"""Token authentication for the ailab web API.

The web daemon manages privileged LXD containers and exposes interactive
shells over WebSockets, so every /api/* request must present a bearer token.
Without this, any web page open in a local browser could drive the API —
WebSockets are not protected by CORS/same-origin policy, so a drive-by page
could otherwise open ws://127.0.0.1:11500/api/ws/shell/<name> and get a
shell inside a privileged container.

The token is generated on first daemon start and persisted:

    Snap:     $SNAP_COMMON/web-token   (root-owned, 0600)
    Non-snap: ~/.local/share/ailab/web-token (user-owned, 0600)

Clients present it as ``Authorization: Bearer <token>`` or, for WebSocket
and browser-navigation cases where headers can't be set, ``?token=<token>``.
`ailab dashboard` prints a ready-to-open tokenized URL.
"""

import logging
import os
import secrets
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from ailab.container import _ailab_data_root

logger = logging.getLogger("ailab.web.auth")

TOKEN_FILE_NAME = "web-token"

# WebSocket close code for failed auth (4000-4999 = application-defined).
_WS_POLICY_VIOLATION = 4401

# Hosts that are always acceptable in a browser Origin header: the dashboard
# itself is served from a loopback address. Anything else must be an
# explicitly configured tunnel-hub origin.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def token_file_path() -> str:
    return str(_ailab_data_root() / TOKEN_FILE_NAME)


def read_token() -> str | None:
    """Return the persisted API token, or None if not created/readable."""
    try:
        with open(token_file_path()) as f:
            token = f.read().strip()
        return token or None
    except OSError:
        return None


def get_or_create_token() -> str:
    """Load the persisted API token, generating it on first run."""
    token = read_token()
    if token:
        return token
    token = secrets.token_urlsafe(32)
    path = token_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    logger.info("Generated new web API token at %s", path)
    return token


def _origin_allowed(origin: str, hub_host: str | None, request_host: str | None = None) -> bool:
    """Return True if a browser Origin header is acceptable.

    Loopback origins (the dashboard served locally) are always fine; the
    configured cloud-tunnel hub — or any of its device subdomains, e.g.
    https://mydevice.cloud.example.com — is fine. So is any origin whose
    host:port exactly matches the Host header the browser used to reach
    this server (request_host) — that's a same-origin request regardless
    of whether the dashboard is bound to loopback, a LAN address, or a
    public IP (`ailab web --host 0.0.0.0`); a cross-site page can't forge
    the browser's Origin header to match, so this widens reachability
    without weakening the check. Anything else is a cross-site request
    and gets rejected.
    """
    try:
        parsed = urlsplit(origin)
        host = parsed.hostname or ""
    except ValueError:
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    if hub_host and parsed.scheme in ("http", "https"):
        if host == hub_host or host.endswith("." + hub_host):
            return True
    if request_host and parsed.netloc.lower() == request_host.lower():
        return True
    return False


class TokenAuthMiddleware:
    """Pure ASGI middleware enforcing bearer-token auth on /api/* routes.

    Covers both HTTP and WebSocket scopes (Starlette's BaseHTTPMiddleware
    does not see websockets, which are exactly the endpoints that most need
    protection here). Static assets and the SPA fallback stay open — the
    frontend itself contains no secrets and needs to load so it can show
    the "locked" screen when no token is present.
    """

    def __init__(self, app, token: str, hub_host: str | None = None):
        self.app = app
        self._token = token
        self._hub_host = hub_host

    def _extract_token(self, scope) -> str:
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth = value.decode("latin-1")
                if auth.lower().startswith("bearer "):
                    return auth[7:].strip()
        qs = scope.get("query_string", b"").decode("latin-1")
        values = parse_qs(qs).get("token")
        return values[0] if values else ""

    def _authorized(self, scope) -> bool:
        presented = self._extract_token(scope)
        return bool(presented) and secrets.compare_digest(presented, self._token)

    @staticmethod
    def _origin_header(scope) -> str | None:
        for name, value in scope.get("headers", []):
            if name == b"origin":
                return value.decode("latin-1")
        return None

    @staticmethod
    def _host_header(scope) -> str | None:
        for name, value in scope.get("headers", []):
            if name == b"host":
                return value.decode("latin-1")
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return

        # Browser cross-site protection: WebSocket handshakes bypass CORS,
        # so enforce the Origin allowlist ourselves. Absent Origin means a
        # non-browser client, which the token requirement already covers.
        origin = self._origin_header(scope)
        request_host = self._host_header(scope)
        origin_ok = origin is None or _origin_allowed(origin, self._hub_host, request_host)

        if self._authorized(scope) and origin_ok:
            await self.app(scope, receive, send)
            return

        if not origin_ok:
            logger.warning("Rejected %s request with untrusted Origin %r for %s",
                           scope["type"], origin, scope["path"])

        if scope["type"] == "http":
            body = b'{"detail":"Not authenticated"}'
            await send({
                "type": "http.response.start",
                "status": HTTPStatus.UNAUTHORIZED,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
        else:
            # Must consume the connect event before closing the handshake.
            message = await receive()
            if message["type"] == "websocket.connect":
                await send({"type": "websocket.close", "code": _WS_POLICY_VIOLATION})
