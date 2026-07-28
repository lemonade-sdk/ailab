"""Tests for dashboard-link host selection when `ailab web` binds wide."""

from ailab import network


def test_wildcard_bind_includes_localhost_and_discovered_addresses(monkeypatch):
    monkeypatch.setattr(network, "local_ipv4_addresses", lambda: ["192.168.1.50", "10.0.0.5"])
    for wildcard in ("0.0.0.0", "::", ""):
        assert network.dashboard_hosts(wildcard) == ["localhost", "192.168.1.50", "10.0.0.5"]


def test_wildcard_bind_still_returns_localhost_if_nothing_discovered(monkeypatch):
    monkeypatch.setattr(network, "local_ipv4_addresses", lambda: [])
    assert network.dashboard_hosts("0.0.0.0") == ["localhost"]


def test_loopback_bind_is_localhost_only(monkeypatch):
    monkeypatch.setattr(network, "local_ipv4_addresses", lambda: ["192.168.1.50"])
    for loopback in ("127.0.0.1", "localhost", "::1"):
        assert network.dashboard_hosts(loopback) == ["localhost"]


def test_specific_bind_address_is_used_as_is(monkeypatch):
    monkeypatch.setattr(network, "local_ipv4_addresses", lambda: ["192.168.1.50"])
    assert network.dashboard_hosts("203.0.113.10") == ["203.0.113.10"]


def test_bracket_if_ipv6():
    assert network.bracket_if_ipv6("::1") == "[::1]"
    assert network.bracket_if_ipv6("192.168.1.50") == "192.168.1.50"
    assert network.bracket_if_ipv6("localhost") == "localhost"


def test_local_ipv4_addresses_excludes_loopback():
    # Real network call (no mocking) — just assert the loopback-exclusion
    # invariant holds, since we can't assume any particular LAN address
    # exists in a CI sandbox.
    assert "127.0.0.1" not in network.local_ipv4_addresses()
    assert all(not a.startswith("127.") for a in network.local_ipv4_addresses())
