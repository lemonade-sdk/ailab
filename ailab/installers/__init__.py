"""Installer registry for ailab."""

from .catalog_app import CatalogAppInstaller
from .openclaw import OpenclawInstaller

# Apps with no ailab-specific behavior beyond what CatalogAppInstaller
# already does generically from the nimbus-app-store catalog. The
# description here is only for offline/no-network use (`ailab --help`,
# `ailab packages`) — install-time behavior is entirely catalog-driven.
_SIMPLE_APPS: dict[str, str] = {
    "hermes-agent": "Autonomous AI agent with 60+ built-in tools and 20+ platform integrations",
    "nullclaw": "Lightweight static-binary AI agent gateway (local-first, Zig-built)",
    "odysseus": "Self-hosted AI workspace (chat, documents, research, image generation)",
    "picoclaw": "Ultra-lightweight Go-based AI agent gateway (local-first, 30+ providers)",
    "zeroclaw": "Zero-config autonomous AI agent with HTTP/WebSocket gateway",
}


def _make_simple_installer(app_id: str, description: str) -> type:
    class_name = "".join(part.capitalize() for part in app_id.split("-")) + "Installer"
    return type(class_name, (CatalogAppInstaller,), {
        "app_id": app_id,
        "name": app_id,
        "description": description,
        "onboard_cmd": None,
    })


INSTALLERS: dict[str, type] = {
    app_id: _make_simple_installer(app_id, description)
    for app_id, description in _SIMPLE_APPS.items()
}
# openclaw has real behavior beyond the generic flow (web UI dashboard
# token/WS-path support), so it stays a hand-written subclass.
INSTALLERS["openclaw"] = OpenclawInstaller


def get_installer(name: str):
    cls = INSTALLERS.get(name.lower())
    if cls is None:
        available = ", ".join(sorted(INSTALLERS))
        raise ValueError(f"Unknown package '{name}'. Available: {available}")
    return cls()
