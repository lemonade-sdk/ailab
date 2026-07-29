"""Tests for the doctor diagnostics (formatting + error classification)."""

from ailab import doctor
from ailab.doctor import FAIL, OK, WARN, Check


def test_format_checks_shows_symbols_and_remedies():
    checks = [
        Check("A", OK, "fine"),
        Check("B", FAIL, "broken", "do the thing"),
        Check("C", WARN, "meh", "optional hint"),
    ]
    out = doctor.format_checks(checks)
    assert "✓  A: fine" in out
    assert "✗  B: broken" in out
    assert "do the thing" in out
    # Remedy lines are indented under the check.
    assert "\n       do the thing" in out


def test_classify_permission_error_non_snap(monkeypatch):
    monkeypatch.delenv("SNAP", raising=False)
    check = doctor._classify_connection_error(Exception("permission denied"))
    assert check.status == FAIL
    assert "lxd group" in check.remedy.lower()


def test_classify_permission_error_in_snap(monkeypatch):
    monkeypatch.setenv("SNAP", "/snap/ailab/1")
    check = doctor._classify_connection_error(Exception("not authorized"))
    assert "snap connect ailab:lxd" in check.remedy


def test_classify_generic_connection_error(monkeypatch):
    monkeypatch.delenv("SNAP", raising=False)
    check = doctor._classify_connection_error(Exception("connection refused"))
    assert check.status == FAIL
    assert "lxd" in check.remedy.lower()


def test_format_failure_includes_remedy_and_pointer():
    msg = doctor._format_failure(Check("LXD socket", FAIL, "not found", "install it"))
    assert "LXD socket: not found" in msg
    assert "install it" in msg
    assert "ailab doctor" in msg
