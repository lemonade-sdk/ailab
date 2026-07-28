"""Installer for odysseus inside an ailab container."""

from .catalog_app import CatalogAppInstaller


class OdysseusInstaller(CatalogAppInstaller):
    app_id = "odysseus"
    name = "odysseus"
    description = "Self-hosted AI workspace (chat, documents, research, image generation)"
    onboard_cmd = None
