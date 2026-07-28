"""Installer for nullclaw inside an ailab container."""

from .catalog_app import CatalogAppInstaller


class NullclawInstaller(CatalogAppInstaller):
    app_id = "nullclaw"
    name = "nullclaw"
    description = "Lightweight static-binary AI agent gateway (local-first, Zig-built)"
    onboard_cmd = None
