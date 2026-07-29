"""Tests for CloudConfig parsing/validation (pure, no network)."""

import pytest

from ailab.cloud import CloudConfig


def test_normalize_ports_default_and_dedup():
    assert CloudConfig._normalize_ports("") == [11500]
    assert CloudConfig._normalize_ports("11500, 18789 ,11500") == [11500, 18789]


def test_normalize_ports_rejects_bad_values():
    with pytest.raises(ValueError):
        CloudConfig._normalize_ports("nope")
    with pytest.raises(ValueError):
        CloudConfig._normalize_ports("70000")


def _env(monkeypatch, **kw):
    for key in ("AILAB_CLOUD_HOST", "AILAB_CLOUD_TOKEN", "AILAB_CLOUD_USER",
                "AILAB_CLOUD_DEVICE", "AILAB_CLOUD_PORTS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in kw.items():
        monkeypatch.setenv(key, value)


def test_from_env_disabled_without_host_or_token(monkeypatch):
    _env(monkeypatch)
    assert CloudConfig.from_env() is None
    _env(monkeypatch, AILAB_CLOUD_HOST="cloud.example.com")
    assert CloudConfig.from_env() is None


def test_from_env_strips_scheme_and_sets_secure(monkeypatch):
    _env(monkeypatch, AILAB_CLOUD_HOST="https://cloud.example.com/",
         AILAB_CLOUD_TOKEN="tok", AILAB_CLOUD_USER="alice", AILAB_CLOUD_DEVICE="myhome")
    cfg = CloudConfig.from_env()
    assert cfg.host == "cloud.example.com"
    assert cfg.secure is True
    assert cfg.device_id == "myhome"
    assert cfg.ws_url == "wss://cloud.example.com/tunnel/register"

    _env(monkeypatch, AILAB_CLOUD_HOST="http://localhost:8080",
         AILAB_CLOUD_TOKEN="tok", AILAB_CLOUD_USER="alice")
    cfg = CloudConfig.from_env()
    assert cfg.secure is False
    assert cfg.ws_url == "ws://localhost:8080/tunnel/register"


def test_from_env_requires_user(monkeypatch):
    _env(monkeypatch, AILAB_CLOUD_HOST="cloud.example.com", AILAB_CLOUD_TOKEN="tok")
    with pytest.raises(ValueError):
        CloudConfig.from_env()


def test_from_env_rejects_bad_device_id(monkeypatch):
    _env(monkeypatch, AILAB_CLOUD_HOST="cloud.example.com", AILAB_CLOUD_TOKEN="tok",
         AILAB_CLOUD_USER="alice", AILAB_CLOUD_DEVICE="Not_Valid")
    with pytest.raises(ValueError):
        CloudConfig.from_env()
