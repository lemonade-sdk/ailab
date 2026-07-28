"""Installer for picoclaw inside an ailab container."""

from .catalog_app import CatalogAppInstaller


class PicoClawInstaller(CatalogAppInstaller):
    app_id = "picoclaw"
    name = "picoclaw"
    description = "Ultra-lightweight Go-based AI agent gateway (local-first, 30+ providers)"
    onboard_cmd = None
