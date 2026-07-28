"""Tests for the web API token auth: origin allowlist, token file, middleware."""

import asyncio
import os
import stat

import pytest

from ailab.web import auth


# ── Origin allowlist ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("origin,hub,expected", [
    ("http://localhost:11500", None, True),
    ("http://127.0.0.1:11500", None, True),
    ("https://evil.example.com", None, False),
    ("https://evil.example.com", "cloud.example.com", False),
    ("https://cloud.example.com", "cloud.example.com", True),
    ("https://mydevice.cloud.example.com", "cloud.example.com", True),
    ("https://notcloud.example.com.evil.com", "cloud.example.com", False),
    ("garbage", None, False),
])
def test_origin_allowed(origin, hub, expected):
    assert auth._origin_allowed(origin, hub) is expected


@pytest.mark.parametrize("origin,request_host,expected", [
    # Direct access via a LAN/public IP that the dashboard is bound to
    # (`ailab web --host 0.0.0.0`): Origin and Host agree, so it's genuinely
    # same-origin regardless of the address being non-loopback.
    ("http://203.0.113.10:11500", "203.0.113.10:11500", True),
    ("http://ailab-server.lan:11500", "ailab-server.lan:11500", True),
    # A drive-by page can set Host (the server it's connecting to) but
    # can't forge its own Origin to match — must stay rejected.
    ("https://evil.example.com", "203.0.113.10:11500", False),
    # Port mismatch is not same-origin.
    ("http://203.0.113.10:9999", "203.0.113.10:11500", False),
])
def test_origin_allowed_same_origin_via_host_header(origin, request_host, expected):
    assert auth._origin_allowed(origin, None, request_host) is expected


# ── Token file ─────────────────────────────────────────────────────────────────

def test_token_created_once_and_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("SNAP_COMMON", raising=False)

    token = auth.get_or_create_token()
    assert token and auth.read_token() == token
    # Idempotent: a second call returns the same persisted token.
    assert auth.get_or_create_token() == token

    path = auth.token_file_path()
    assert os.path.exists(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


# ── Bind-host file ───────────────────────────────────────────────────────────

def test_bind_host_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("SNAP_COMMON", raising=False)

    assert auth.read_bind_host() is None  # nothing recorded yet

    auth.write_bind_host("0.0.0.0")
    assert auth.read_bind_host() == "0.0.0.0"

    # A later `ailab web` run with a different --host overwrites it.
    auth.write_bind_host("127.0.0.1")
    assert auth.read_bind_host() == "127.0.0.1"


# ── Middleware ─────────────────────────────────────────────────────────────────

def _scope(path, token=None, origin=None, host=None, scope_type="http"):
    headers = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if host is not None:
        headers.append((b"host", host.encode()))
    query = f"token={token}".encode() if token and "?q" in path else b""
    return {"type": scope_type, "path": path, "headers": headers, "query_string": query}


def _run_http(mw, scope):
    """Drive the middleware for one HTTP request; return (status, downstream_called)."""
    called = {"v": False}

    async def downstream(scope, receive, send):
        called["v"] = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw.app = downstream
    sent = []

    async def receive():
        return {"type": "http.request"}

    async def send(msg):
        sent.append(msg)

    asyncio.run(mw(scope, receive, send))
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    return status, called["v"]


def _make_mw(token="secret", hub=None):
    return auth.TokenAuthMiddleware(app=None, token=token, hub_host=hub)


def test_non_api_paths_bypass_auth():
    mw = _make_mw()
    status, called = _run_http(mw, _scope("/index.html"))
    assert called and status == 200


def test_api_requires_token():
    mw = _make_mw()
    status, called = _run_http(mw, _scope("/api/containers"))
    assert not called and status == 401


def test_api_accepts_correct_token():
    mw = _make_mw()
    status, called = _run_http(mw, _scope("/api/containers", token="secret"))
    assert called and status == 200


def test_api_rejects_wrong_token():
    mw = _make_mw()
    status, called = _run_http(mw, _scope("/api/containers", token="nope"))
    assert not called and status == 401


def test_api_rejects_foreign_origin_even_with_token():
    mw = _make_mw()
    status, called = _run_http(
        mw, _scope("/api/containers", token="secret", origin="https://evil.example.com")
    )
    assert not called and status == 401


def test_api_accepts_matching_origin_from_public_host():
    """`ailab web --host 0.0.0.0` + browsing via the host's public IP: Origin
    and Host agree, so this must work without a cloud tunnel configured."""
    mw = _make_mw()
    status, called = _run_http(
        mw,
        _scope(
            "/api/containers",
            token="secret",
            origin="http://203.0.113.10:11500",
            host="203.0.113.10:11500",
        ),
    )
    assert called and status == 200


def test_api_rejects_foreign_origin_even_with_matching_host_present():
    """A drive-by page can make the browser send Host: <ailab-host>, but it
    can't forge its own Origin — must stay rejected even with a token."""
    mw = _make_mw()
    status, called = _run_http(
        mw,
        _scope(
            "/api/containers",
            token="secret",
            origin="https://evil.example.com",
            host="203.0.113.10:11500",
        ),
    )
    assert not called and status == 401
