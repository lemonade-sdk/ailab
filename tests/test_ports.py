"""Tests for proxy-device conflict partitioning and port sort key."""

from ailab import container


def test_port_sort_key_orders_numerically():
    ports = ["8000", "18789", "80", "abc"]
    assert sorted(ports, key=container._port_sort_key) == ["80", "8000", "18789", "abc"]


def test_partition_conflicting_proxies(monkeypatch):
    in_use = {18789}
    monkeypatch.setattr(container, "_host_port_in_use", lambda p: p in in_use)

    devices = {
        "homedir": {"type": "disk", "source": "/x", "path": "/home/u"},
        # Outbound (host-bound) proxy whose port is busy -> conflicting.
        "proxy-out-openclaw-18789": {
            "type": "proxy", "bind": "host",
            "listen": "tcp:127.0.0.1:18789", "connect": "tcp:127.0.0.1:18789",
        },
        # Outbound proxy on a free port -> safe.
        "proxy-out-web-9000": {
            "type": "proxy", "bind": "host",
            "listen": "tcp:127.0.0.1:9000", "connect": "tcp:127.0.0.1:9000",
        },
        # Inbound (container-bound) proxy -> never treated as a host conflict.
        "proxy-in-lemonade": {
            "type": "proxy", "bind": "container",
            "listen": "tcp:127.0.0.1:18789", "connect": "tcp:127.0.0.1:18789",
        },
    }

    conflicting, rest = container._partition_conflicting_proxies(devices)

    assert set(conflicting) == {"proxy-out-openclaw-18789"}
    assert set(rest) == {"homedir", "proxy-out-web-9000", "proxy-in-lemonade"}


def test_host_port_probe_uses_connect_not_bind():
    # A port nothing listens on should read as free (connect_ex != 0).
    assert container._host_port_in_use(1) is False
