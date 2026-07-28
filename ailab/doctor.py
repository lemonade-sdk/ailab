"""Environment diagnostics for ailab.

Powers `ailab doctor` (a full report) and the pre-flight checks that run
before `ailab new` so the common setup mistakes — LXD not installed, never
initialised, the snap's lxd interface not connected, or the user not in the
lxd group — surface as a clear message with a remedy instead of a raw pylxd
traceback.
"""

import os
import socket
from dataclasses import dataclass

import pylxd.exceptions

from .container import AILAB_PROJECT, _admin_client, _find_lxd_socket

OK = "ok"
WARN = "warn"
FAIL = "fail"

_SYMBOL = {OK: "✓", WARN: "!", FAIL: "✗"}


@dataclass
class Check:
    name: str
    status: str
    detail: str
    remedy: str = ""


class DoctorError(RuntimeError):
    """Raised by preflight() when a required environment check fails."""


def _in_snap() -> bool:
    return bool(os.environ.get("SNAP"))


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


# ── Individual checks ──────────────────────────────────────────────────────────

def _check_lxd_socket() -> Check:
    try:
        path = _find_lxd_socket()
    except FileNotFoundError:
        if _in_snap():
            return Check(
                "LXD socket", FAIL,
                "not found — the snap cannot see LXD",
                "Connect the interface:  sudo snap connect ailab:lxd lxd:lxd\n"
                "(install LXD first if needed:  sudo snap install lxd)",
            )
        return Check(
            "LXD socket", FAIL,
            "not found — LXD does not appear to be installed",
            "Install and initialise LXD:  sudo snap install lxd && sudo lxd init --auto",
        )
    return Check("LXD socket", OK, f"found at {path}")


def _classify_connection_error(exc: Exception) -> Check:
    text = str(exc).lower()
    permission = any(s in text for s in ("permission denied", "forbidden", "not authorized", "403"))
    if permission:
        if _in_snap():
            return Check(
                "LXD connection", FAIL, "permission denied talking to LXD",
                "Connect the interface:  sudo snap connect ailab:lxd lxd:lxd",
            )
        return Check(
            "LXD connection", FAIL, "permission denied talking to LXD",
            "Add your user to the lxd group:  sudo usermod -aG lxd $USER\n"
            "then apply it:  newgrp lxd   (or log out and back in)",
        )
    return Check(
        "LXD connection", FAIL, f"could not connect to LXD: {exc}",
        "Is the LXD daemon running?  sudo snap start lxd",
    )


def _check_lxd_api() -> Check:
    try:
        # Constructing the client performs a GET /1.0 handshake, so this
        # round-trips the daemon and surfaces permission errors.
        client = _admin_client()
        _ = client.host_info
    except Exception as exc:  # pylxd raises several unrelated types here
        return _classify_connection_error(exc)
    return Check("LXD connection", OK, "connected")


def _check_lxd_initialised() -> Check:
    try:
        devices = _admin_client().profiles.get("default").devices
    except Exception as exc:
        return Check("LXD storage/network", WARN, f"could not read the default profile: {exc}")
    has_disk = any(d.get("type") == "disk" for d in devices.values())
    has_nic = any(d.get("type") == "nic" for d in devices.values())
    if has_disk and has_nic:
        return Check("LXD storage/network", OK, "default profile has a storage pool and a network")
    missing = []
    if not has_disk:
        missing.append("storage pool")
    if not has_nic:
        missing.append("network")
    return Check(
        "LXD storage/network", FAIL,
        f"default profile is missing: {', '.join(missing)}",
        "Initialise LXD:  sudo lxd init --auto",
    )


def _check_ailab_project() -> Check:
    try:
        _admin_client().projects.get(AILAB_PROJECT)
    except pylxd.exceptions.NotFound:
        return Check("ailab project", OK, "not created yet (created automatically on first use)")
    except Exception as exc:
        return Check("ailab project", WARN, f"could not check: {exc}")
    return Check("ailab project", OK, "present")


def _check_lemonade() -> Check:
    for port in (13305, 8000):
        if _port_open(port):
            return Check("lemonade-server", OK, f"reachable on 127.0.0.1:{port}")
    return Check(
        "lemonade-server", WARN,
        "not reachable on 127.0.0.1:13305 or :8000",
        "Start it on the host for local AI:  lemonade-server serve\n"
        "(containers still work without it, but no local model will be available)",
    )


def _check_ollama() -> Check:
    if _port_open(11434):
        return Check("ollama", OK, "reachable on 127.0.0.1:11434")
    return Check("ollama", WARN, "not reachable on 127.0.0.1:11434 (optional)")


# ── Runners ────────────────────────────────────────────────────────────────────

def run_checks() -> list[Check]:
    """Run every diagnostic and return the results in report order."""
    checks: list[Check] = [_check_lxd_socket()]
    if checks[0].status != FAIL:
        api = _check_lxd_api()
        checks.append(api)
        if api.status == OK:
            checks.append(_check_lxd_initialised())
            checks.append(_check_ailab_project())
    checks.append(_check_lemonade())
    checks.append(_check_ollama())
    return checks


def format_checks(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        lines.append(f"  {_SYMBOL[c.status]}  {c.name}: {c.detail}")
        if c.remedy and c.status != OK:
            for remedy_line in c.remedy.split("\n"):
                lines.append(f"       {remedy_line}")
    return "\n".join(lines)


def _format_failure(c: Check) -> str:
    msg = f"{c.name}: {c.detail}"
    if c.remedy:
        msg += "\n\n" + c.remedy
    msg += "\n\nRun 'ailab doctor' for a full environment check."
    return msg


def preflight() -> None:
    """Run the LXD-critical checks; raise DoctorError on the first failure.

    Called before container creation so setup problems produce a friendly
    message instead of a pylxd traceback deep in the create path.
    """
    socket_check = _check_lxd_socket()
    if socket_check.status == FAIL:
        raise DoctorError(_format_failure(socket_check))
    api = _check_lxd_api()
    if api.status == FAIL:
        raise DoctorError(_format_failure(api))
    init = _check_lxd_initialised()
    if init.status == FAIL:
        raise DoctorError(_format_failure(init))
