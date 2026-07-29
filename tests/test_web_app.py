"""Tests for the web app's port-base-URL resolution (direct vs. tunnel access)."""

from starlette.requests import Request

from ailab.web.app import _port_base_url


def _make_request(host_header, tunnel_base=None, client_host="127.0.0.1"):
    headers = [(b"host", host_header.encode())]
    if tunnel_base is not None:
        headers.append((b"x-ailab-tunnel-base", tunnel_base.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "query_string": b"",
        "client": (client_host, 12345),
        "server": ("0.0.0.0", 11500),
        "scheme": "http",
    }
    return Request(scope)


def test_local_access_uses_loopback():
    assert _port_base_url(_make_request("localhost:11500")) == "http://localhost"
    assert _port_base_url(_make_request("127.0.0.1:11500")) == "http://127.0.0.1"


def test_public_host_access_reflects_the_address_the_browser_used():
    """`ailab web --host 0.0.0.0` reached via a LAN/public IP: gateway links
    must point back at that address, not the browser's own localhost."""
    assert _port_base_url(_make_request("203.0.113.10:11500")) == "http://203.0.113.10"


def test_tunnel_header_from_trusted_local_client_wins():
    req = _make_request(
        "localhost:11500",
        tunnel_base="https://hub.example.com/d/mydevice",
        client_host="127.0.0.1",
    )
    assert _port_base_url(req) == "https://hub.example.com/d/mydevice"


def test_tunnel_header_from_untrusted_client_is_ignored():
    req = _make_request(
        "203.0.113.10:11500",
        tunnel_base="https://hub.example.com/d/mydevice",
        client_host="203.0.113.10",
    )
    assert _port_base_url(req) == "http://203.0.113.10"
