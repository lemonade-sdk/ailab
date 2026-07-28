"""Installer for hermes-agent inside an ailab container."""

from .catalog_app import CatalogAppInstaller


class HermesAgentInstaller(CatalogAppInstaller):
    app_id = "hermes-agent"
    name = "hermes-agent"
    description = "Autonomous AI agent with 60+ built-in tools and 20+ platform integrations"
    onboard_cmd = None
