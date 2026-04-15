"""Cloud tunnel client for AI Lab.

Connects outbound to an ailab-cloud hub over a persistent WebSocket, then
forwards HTTP requests and WebSocket connections from the hub to local ports
on this machine.

Configuration (all optional — cloud tunnel is disabled when host/token are absent):

    AILAB_CLOUD_HOST    Hub hostname or URL, e.g. cloud.example.com or http://localhost:8080
    AILAB_CLOUD_TOKEN   Tunnel registration token from the hub dashboard
    AILAB_CLOUD_USER    GitHub username registered on the hub
    AILAB_CLOUD_DEVICE  Device ID to register (default: system hostname)
    AILAB_CLOUD_PORTS   Comma-separated list of ports to advertise (e.g. "11500,18789")

Usage from ailab web app:

    from ailab.cloud import CloudTunnelManager
    manager = CloudTunnelManager.from_env()
    if manager:
        await manager.start()
        ...
        await manager.stop()

Protocol (JSON over WebSocket text frames)
------------------------------------------
Home device → Hub:
  {"type": "register",  "github_user": "...", "device_id": "...",
                        "ports": [...], "token": "..."}
  {"type": "response",  "id": "<uuid>",    "status": 200, "headers": {...}, "body": "<base64>"}
  {"type": "ws_opened", "conn_id": "<uuid>"}
  {"type": "ws_error",  "conn_id": "<uuid>", "error": "..."}
  {"type": "ws_frame",  "conn_id": "<uuid>", "opcode": 1|2, "data": "<base64>"}
  {"type": "ws_close",  "conn_id": "<uuid>"}

Hub → Home device:
  {"type": "registered"}
  {"type": "request",   "id": "<uuid>",      "method": "...", "path": "...",
                        "port": 11500, "headers": {...}, "body": "<base64>"}
  {"type": "ws_open",   "conn_id": "<uuid>", "port": ..., "path": "...",
                        "headers": {...}}
  {"type": "ws_frame",  "conn_id": "<uuid>", "opcode": 1|2, "data": "<base64>"}
  {"type": "ws_close",  "conn_id": "<uuid>"}
"""

import asyncio
import base64
import binascii
import json
import logging
import os
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

logger = logging.getLogger("ailab.cloud")

_DEVICE_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_HEARTBEAT_INTERVAL = 30
_REGISTER_TIMEOUT = 15
_LOCAL_PROXY_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=5, sock_connect=5, sock_read=60)

# Reconnect delay: start at 2 s, double each attempt, cap at 60 s.
_BACKOFF_BASE = 2
_BACKOFF_MAX = 60

# Hop-by-hop headers that must not be forwarded.
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers",
    "transfer-encoding", "upgrade",
})


@dataclass
class CloudConfig:
    host: str
    token: str
    github_user: str
    device_id: str
    secure: bool = True
    ports: list[int] = field(default_factory=list)

    @staticmethod
    def _normalize_ports(ports_raw: str) -> list[int]:
        if not ports_raw:
            return [11500]

        ports: list[int] = []
        seen: set[int] = set()
        for item in ports_raw.split(","):
            item = item.strip()
            if not item:
                continue
            if not item.isdigit():
                raise ValueError(f"Invalid port value: {item!r}")
            port = int(item)
            if not 1 <= port <= 65535:
                raise ValueError(f"Port out of range: {port}")
            if port not in seen:
                ports.append(port)
                seen.add(port)

        if not ports:
            raise ValueError("At least one cloud port must be configured")

        return ports

    @classmethod
    def from_env(cls) -> "CloudConfig | None":
        host = os.environ.get("AILAB_CLOUD_HOST", "").strip()
        token = os.environ.get("AILAB_CLOUD_TOKEN", "").strip()
        if not host or not token:
            return None
        secure = True
        # Strip any scheme the user may have included (e.g. "https://host" → "host").
        for scheme in ("https://", "http://", "wss://", "ws://"):
            if host.startswith(scheme):
                secure = scheme in ("https://", "wss://")
                host = host[len(scheme):]
                break
        host = host.rstrip("/")
        github_user = os.environ.get("AILAB_CLOUD_USER", "").strip()
        if not github_user:
            raise ValueError("AILAB_CLOUD_USER is required when cloud tunnel is enabled")
        device_id = os.environ.get("AILAB_CLOUD_DEVICE", "").strip() or socket.gethostname()
        ports_raw = os.environ.get("AILAB_CLOUD_PORTS", "").strip()
        if not _DEVICE_ID_RE.fullmatch(device_id):
            raise ValueError(
                f"Invalid AILAB_CLOUD_DEVICE {device_id!r}; use lowercase letters, digits, and hyphens"
            )
        ports = cls._normalize_ports(ports_raw)
        return cls(
            host=host,
            token=token,
            github_user=github_user,
            device_id=device_id,
            secure=secure,
            ports=ports,
        )

    @property
    def ws_url(self) -> str:
        scheme = "wss" if self.secure else "ws"
        return f"{scheme}://{self.host}/tunnel/register"


class CloudTunnelManager:
    """Manages a persistent WebSocket tunnel to the ailab-cloud hub."""

    def __init__(self, config: CloudConfig) -> None:
        self._config = config
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        # Active proxied WebSocket connections keyed by conn_id.
        self._ws_connections: dict[str, aiohttp.ClientWebSocketResponse] = {}
        self._local_session: aiohttp.ClientSession | None = None
        self._tunnel_ws: aiohttp.ClientWebSocketResponse | None = None

    async def _await_registered(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        msg = await ws.receive(timeout=_REGISTER_TIMEOUT)

        if msg.type != aiohttp.WSMsgType.TEXT:
            if msg.type == aiohttp.WSMsgType.ERROR and ws.exception():
                raise RuntimeError(f"Tunnel registration failed: {ws.exception()}")
            raise RuntimeError(
                f"Tunnel registration failed before acknowledgement (type={msg.type})"
            )

        try:
            envelope = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Tunnel registration returned non-JSON data") from exc

        if envelope.get("type") != "registered":
            raise RuntimeError(
                f"Tunnel registration failed: unexpected message {envelope.get('type')!r}"
            )

        logger.info("Registered with hub as device '%s'", self._config.device_id)

    @classmethod
    def from_env(cls) -> "CloudTunnelManager | None":
        config = CloudConfig.from_env()
        if config is None:
            return None
        return cls(config)

    async def start(self) -> None:
        """Start the background reconnect loop."""
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="cloud-tunnel")
        logger.info(
            "Cloud tunnel started — hub: %s  device: %s",
            self._config.host,
            self._config.device_id,
        )

    async def stop(self) -> None:
        """Signal the reconnect loop to exit and wait for it."""
        self._stop_event.set()
        if self._tunnel_ws and not self._tunnel_ws.closed:
            await self._tunnel_ws.close()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        await self._close_local_proxies()
        logger.info("Cloud tunnel stopped")

    async def _close_local_proxies(self) -> None:
        """Close all local proxy sockets and the shared local client session."""
        for local_ws in list(self._ws_connections.values()):
            if not local_ws.closed:
                try:
                    await local_ws.close()
                except Exception:
                    pass
        self._ws_connections.clear()

        local_session = self._local_session
        self._local_session = None
        if local_session and not local_session.closed:
            await local_session.close()

    # ── Internal reconnect loop ───────────────────────────────────────────────

    async def _run(self) -> None:
        delay = _BACKOFF_BASE
        while not self._stop_event.is_set():
            try:
                await self._connect_and_serve()
                delay = _BACKOFF_BASE  # reset on clean disconnect
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("Tunnel disconnected: %s — reconnecting in %ds", exc, delay)

            if self._stop_event.is_set():
                return
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, _BACKOFF_MAX)

    async def _connect_and_serve(self) -> None:
        cfg = self._config
        connector = aiohttp.TCPConnector(ssl=cfg.secure)
        async with aiohttp.ClientSession(connector=connector) as session:
            self._local_session = aiohttp.ClientSession(timeout=_LOCAL_PROXY_TIMEOUT)
            try:
                logger.info("Connecting to hub at %s", cfg.ws_url)
                async with session.ws_connect(
                    cfg.ws_url,
                    heartbeat=_HEARTBEAT_INTERVAL,
                ) as ws:
                    self._tunnel_ws = ws
                    logger.info("Tunnel WebSocket connected")

                    # Send registration message.
                    await ws.send_json({
                        "type": "register",
                        "github_user": cfg.github_user,
                        "device_id": cfg.device_id,
                        "ports": cfg.ports,
                        "token": cfg.token,
                    })

                    await self._await_registered(ws)

                    try:
                        async for msg in ws:
                            if self._stop_event.is_set():
                                return
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    envelope = json.loads(msg.data)
                                except json.JSONDecodeError:
                                    logger.warning("Received non-JSON message from hub")
                                    continue
                                await self._dispatch(ws, self._local_session, envelope)
                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                logger.info("Tunnel WS closed (type=%s)", msg.type)
                                break
                    finally:
                        self._tunnel_ws = None

                    if self._stop_event.is_set():
                        return

                    if ws.exception():
                        raise RuntimeError(f"Tunnel socket error: {ws.exception()}")

                    raise RuntimeError(
                        f"Tunnel closed by hub (code={ws.close_code})"
                    )
            finally:
                await self._close_local_proxies()

    # ── Envelope dispatch ─────────────────────────────────────────────────────

    async def _dispatch(
        self,
        tunnel_ws: aiohttp.ClientWebSocketResponse,
        local_session: aiohttp.ClientSession,
        envelope: dict,
    ) -> None:
        msg_type = envelope.get("type")
        if msg_type == "request":
            asyncio.create_task(self._handle_http(tunnel_ws, local_session, envelope))
        elif msg_type == "ws_open":
            asyncio.create_task(self._handle_ws_open(tunnel_ws, local_session, envelope))
        elif msg_type == "ws_frame":
            await self._handle_ws_frame(envelope)
        elif msg_type == "ws_close":
            await self._handle_ws_close(envelope)
        else:
            logger.debug("Unknown envelope type: %s", msg_type)

    # ── HTTP proxy ────────────────────────────────────────────────────────────

    async def _handle_http(
        self,
        tunnel_ws: aiohttp.ClientWebSocketResponse,
        local_session: aiohttp.ClientSession,
        envelope: dict,
    ) -> None:
        req_id = envelope.get("id", "")
        port = envelope.get("port", 80)
        method = envelope.get("method", "GET").upper()
        path = envelope.get("path", "/")
        headers = dict(envelope.get("headers", {}))
        body_b64 = envelope.get("body", "")

        if port not in self._config.ports:
            response_envelope = {
                "type": "response",
                "id": req_id,
                "status": 403,
                "headers": {},
                "body": "",
                "error": f"Port {port} is not exposed by this device",
            }
            await tunnel_ws.send_json(response_envelope)
            return

        fwd_headers = {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP}

        url = f"http://127.0.0.1:{port}{path}"
        try:
            body: bytes | None = base64.b64decode(body_b64, validate=True) if body_b64 else None
            async with local_session.request(
                method, url, headers=fwd_headers, data=body, allow_redirects=False
            ) as resp:
                resp_body = await resp.read()
                resp_headers = {
                    k: v for k, v in resp.headers.items()
                    if k.lower() not in _HOP_BY_HOP
                }
                response_envelope = {
                    "type": "response",
                    "id": req_id,
                    "status": resp.status,
                    "headers": resp_headers,
                    "body": base64.b64encode(resp_body).decode(),
                }
        except (binascii.Error, ValueError) as exc:
            logger.warning("HTTP proxy request body decode error for %s %s: %s", method, url, exc)
            response_envelope = {
                "type": "response",
                "id": req_id,
                "status": 400,
                "headers": {},
                "body": "",
                "error": f"Invalid base64 request body: {exc}",
            }
        except Exception as exc:
            logger.warning("HTTP proxy error for %s %s: %s", method, url, exc)
            response_envelope = {
                "type": "response",
                "id": req_id,
                "status": 502,
                "headers": {},
                "body": "",
                "error": str(exc),
            }

        try:
            await tunnel_ws.send_json(response_envelope)
        except Exception as exc:
            logger.warning("Failed to send HTTP response to hub: %s", exc)

    # ── WebSocket proxy ───────────────────────────────────────────────────────

    async def _handle_ws_open(
        self,
        tunnel_ws: aiohttp.ClientWebSocketResponse,
        local_session: aiohttp.ClientSession,
        envelope: dict,
    ) -> None:
        conn_id = envelope.get("conn_id", "")
        port = envelope.get("port", 80)
        path = envelope.get("path", "/")

        if port not in self._config.ports:
            await tunnel_ws.send_json({
                "type": "ws_error",
                "conn_id": conn_id,
                "error": f"Port {port} is not exposed by this device",
            })
            return

        # Extract a `token` query param injected by the ailab web app for
        # services that require Authorization: Bearer (e.g. openclaw gateway).
        # Strip it from the local URL so the service doesn't see a stray param.
        parsed_path = urlparse(path)
        qs = parse_qs(parsed_path.query, keep_blank_values=True)
        extra_headers: dict[str, str] = {}
        if "token" in qs:
            extra_headers["Authorization"] = f"Bearer {qs.pop('token')[0]}"
        clean_qs = urlencode({k: v[0] for k, v in qs.items()})
        local_path = parsed_path._replace(query=clean_qs).geturl()
        url = f"ws://127.0.0.1:{port}{local_path}"

        # Forward browser headers sent by the hub (e.g. Origin) so local
        # services that enforce CORS on WS upgrades see the real browser origin.
        fwd_headers: dict = envelope.get("headers", {})
        for k, v in fwd_headers.items():
            extra_headers.setdefault(k.capitalize(), v)

        try:
            local_ws = await local_session.ws_connect(url, headers=extra_headers or None)
            self._ws_connections[conn_id] = local_ws

            # Acknowledge the open.
            await tunnel_ws.send_json({"type": "ws_opened", "conn_id": conn_id})
            logger.debug("WS proxy opened conn=%s → %s", conn_id, url)

            # Start relay task: local → tunnel.
            asyncio.create_task(
                self._relay_local_to_tunnel(conn_id, local_ws, tunnel_ws),
                name=f"ws-relay-{conn_id}",
            )
        except Exception as exc:
            logger.warning("WS proxy open failed conn=%s url=%s: %s", conn_id, url, exc)
            await tunnel_ws.send_json({"type": "ws_error", "conn_id": conn_id, "error": str(exc)})

    async def _relay_local_to_tunnel(
        self,
        conn_id: str,
        local_ws: aiohttp.ClientWebSocketResponse,
        tunnel_ws: aiohttp.ClientWebSocketResponse,
    ) -> None:
        """Forward frames from a local service WS to the hub tunnel."""
        try:
            async for msg in local_ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await tunnel_ws.send_json({
                        "type": "ws_frame",
                        "conn_id": conn_id,
                        "opcode": 1,
                        "data": base64.b64encode(msg.data.encode()).decode(),
                    })
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await tunnel_ws.send_json({
                        "type": "ws_frame",
                        "conn_id": conn_id,
                        "opcode": 2,
                        "data": base64.b64encode(msg.data).decode(),
                    })
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except Exception as exc:
            logger.debug("WS relay error conn=%s: %s", conn_id, exc)
        finally:
            self._ws_connections.pop(conn_id, None)
            try:
                await tunnel_ws.send_json({"type": "ws_close", "conn_id": conn_id})
            except Exception:
                pass

    async def _handle_ws_frame(self, envelope: dict) -> None:
        """Forward a frame from the hub to the local WebSocket connection."""
        conn_id = envelope.get("conn_id", "")
        local_ws = self._ws_connections.get(conn_id)
        if local_ws is None or local_ws.closed:
            return
        opcode = envelope.get("opcode", 1)
        try:
            data = base64.b64decode(envelope.get("data", ""), validate=True)
        except (binascii.Error, ValueError) as exc:
            logger.warning("WS frame decode error conn=%s: %s", conn_id, exc)
            await self._handle_ws_close({"conn_id": conn_id})
            return
        try:
            if opcode == 2:
                await local_ws.send_bytes(data)
            else:
                await local_ws.send_str(data.decode())
        except Exception as exc:
            logger.debug("WS frame send error conn=%s: %s", conn_id, exc)

    async def _handle_ws_close(self, envelope: dict) -> None:
        """Close a proxied local WebSocket connection."""
        conn_id = envelope.get("conn_id", "")
        local_ws = self._ws_connections.pop(conn_id, None)
        if local_ws and not local_ws.closed:
            try:
                await local_ws.close()
            except Exception:
                pass
        logger.debug("WS proxy closed conn=%s", conn_id)
