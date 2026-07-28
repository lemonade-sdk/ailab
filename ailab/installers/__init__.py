"""Installer registry for ailab."""

from .. import appstore
from .catalog_app import CatalogAppInstaller
from .openclaw import OpenclawInstaller

# Apps with no ailab-specific behavior beyond what CatalogAppInstaller
# already does generically from the nimbus-app-store catalog.
#
# This table is only a fallback, used for --help text, shell completion,
# and `ailab packages` when the catalog can't be reached. It is NOT the
# source of truth for what's installable — get_installer() always checks
# the live catalog first, so a new app added to nimbus-app-store is
# installable via `ailab install` immediately, without an ailab release.
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
    name = name.lower()

    # Check the live catalog first — this is what lets a new app added to
    # nimbus-app-store install via `ailab install` with no ailab changes.
    catalog = appstore.get_catalog()
    snap = appstore.get_snap(catalog, name)
    if snap is not None:
        description = snap.get("summary") or snap.get("title") or name
        if name == "openclaw":
            inst = OpenclawInstaller()
        else:
            inst = _make_simple_installer(name, description)()
        inst.description = description
        return inst

    # Catalog unreachable or app not (yet) listed there — fall back to the
    # static table so the apps we already know about keep working offline.
    cls = INSTALLERS.get(name)
    if cls is not None:
        return cls()

    available = ", ".join(sorted(INSTALLERS))
    raise ValueError(f"Unknown package '{name}'. Available: {available}")
