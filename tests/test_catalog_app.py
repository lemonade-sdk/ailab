"""Tests for CatalogAppInstaller: reinstall handling, install flags, and
that service actions never go through a shell (service_name is untrusted,
sourced live from the nimbus-app-store catalog)."""

import pytest

from ailab.installers import catalog_app as ca


SNAP = {
    "name": "nullclaw",
    "store_name": "nullclaw",
    "ports": [3002],
    "install_flags": ["--classic", "--devmode"],
}


class FakeInstaller(ca.CatalogAppInstaller):
    app_id = "nullclaw"
    name = "nullclaw"
    description = "test"
    onboard_cmd = None


def _patch_common(monkeypatch, install_result=(0, "", "")):
    """Stub every catalog_app dependency except the install command itself,
    which the caller controls via install_result (exit_code, stdout, stderr)."""
    monkeypatch.setattr(ca, "_container_name", lambda name: name)
    monkeypatch.setattr(ca, "_container_status", lambda cname: "running")
    monkeypatch.setattr(ca, "get_container_user", lambda cname: ("user", 1000, 1000, "/home/user"))
    monkeypatch.setattr(ca, "start_container", lambda cname: None)
    monkeypatch.setattr(ca, "has_device", lambda cname, dev: False)
    monkeypatch.setattr(ca, "add_proxy_device", lambda *a, **k: True)
    monkeypatch.setattr(ca.appstore, "get_catalog", lambda: {"snaps": [SNAP], "base_url": ""})

    calls = []

    def fake_exec(cname, cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:2] == ["snap", "install"]:
            return install_result
        return (0, "", "")

    monkeypatch.setattr(ca, "container_exec", fake_exec)
    return calls


def test_install_command_includes_all_catalog_flags(monkeypatch):
    calls = _patch_common(monkeypatch)
    FakeInstaller().install("box")

    install_call = next(cmd for cmd, _ in calls if cmd[:2] == ["snap", "install"])
    assert install_call == ["snap", "install", "nullclaw", "--classic", "--devmode"]


def test_install_survives_already_installed_error(monkeypatch):
    calls = _patch_common(
        monkeypatch,
        install_result=(1, "", 'snap "nullclaw" is already installed, see \'snap help refresh\'\n'),
    )
    # Must not raise — reinstalling is how `ailab install` re-runs onboarding.
    FakeInstaller().install("box")
    assert any(cmd[:2] == ["snap", "install"] for cmd, _ in calls)


def test_install_raises_on_genuine_install_failure(monkeypatch):
    _patch_common(monkeypatch, install_result=(1, "", "error: cannot communicate with server\n"))
    with pytest.raises(RuntimeError, match="cannot communicate with server"):
        FakeInstaller().install("box")


def test_service_action_never_uses_a_shell(monkeypatch):
    """service_name comes from the live catalog; if it ever contained shell
    metacharacters it must still be passed through as a single argv element,
    never interpolated into a `bash -c` string."""
    calls = []
    monkeypatch.setattr(ca, "container_exec", lambda cname, cmd, **k: calls.append(cmd) or (0, "", ""))

    malicious_service_name = "x; rm -rf ~"
    FakeInstaller()._service_action("box", 1000, 1000, {}, malicious_service_name, "restart")

    assert all("bash" not in cmd for cmd in calls), calls
    assert any(cmd == ["systemctl", "--user", "restart", malicious_service_name] for cmd in calls), calls
