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


# ── add_port / remove_port ──────────────────────────────────────────────────

class _FakeInstance:
    def __init__(self, devices):
        self.devices = devices
        self.saved = 0

    @property
    def expanded_devices(self):
        return self.devices

    def save(self, wait=True):
        self.saved += 1


def _patch_instance(monkeypatch, instance):
    monkeypatch.setattr(container, "_container_status", lambda cname: "running")
    monkeypatch.setattr(container, "_get_instance", lambda cname: instance)


def test_remove_inbound_port_finds_device_by_container_side_port(monkeypatch):
    """add_port(..., direction='inbound') names the device after the
    container-side port, not the host-side one it forwards to — removal
    must locate it by matching either side, not by reconstructing the name
    from whatever single port number the caller passed."""
    instance = _FakeInstance({
        # container listens on 9000, forwards to host's port 9001 —
        # host_port (9001) and container_port (9000) deliberately differ.
        "proxy-in-custom-9000": {
            "type": "proxy", "bind": "container",
            "listen": "tcp:127.0.0.1:9000", "connect": "tcp:127.0.0.1:9001",
        },
    })
    _patch_instance(monkeypatch, instance)

    container.remove_port("box", 9001, "inbound")  # host-side port

    assert "proxy-in-custom-9000" not in instance.devices


def test_remove_inbound_port_also_matches_container_side_port(monkeypatch):
    instance = _FakeInstance({
        "proxy-in-custom-9000": {
            "type": "proxy", "bind": "container",
            "listen": "tcp:127.0.0.1:9000", "connect": "tcp:127.0.0.1:9001",
        },
    })
    _patch_instance(monkeypatch, instance)

    container.remove_port("box", 9000, "inbound")  # container-side port

    assert "proxy-in-custom-9000" not in instance.devices


def test_remove_inbound_port_reports_when_nothing_matches(monkeypatch, capsys):
    instance = _FakeInstance({})
    _patch_instance(monkeypatch, instance)

    container.remove_port("box", 55555, "inbound")

    assert "No inbound proxy found on port 55555" in capsys.readouterr().out
