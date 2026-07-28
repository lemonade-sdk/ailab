"""Installer for zeroclaw inside an ailab container."""

from .catalog_app import CatalogAppInstaller


class ZeroclawInstaller(CatalogAppInstaller):
    app_id = "zeroclaw"
    name = "zeroclaw"
    description = "Zero-config autonomous AI agent with HTTP/WebSocket gateway"
    onboard_cmd = None
