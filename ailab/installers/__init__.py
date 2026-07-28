"""Installer registry for ailab."""

from .hermes_agent import HermesAgentInstaller
from .nullclaw import NullclawInstaller
from .odysseus import OdysseusInstaller
from .openclaw import OpenclawInstaller
from .picoclaw import PicoClawInstaller
from .zeroclaw import ZeroclawInstaller

INSTALLERS: dict[str, type] = {
    "hermes-agent": HermesAgentInstaller,
    "nullclaw": NullclawInstaller,
    "odysseus": OdysseusInstaller,
    "openclaw": OpenclawInstaller,
    "picoclaw": PicoClawInstaller,
    "zeroclaw": ZeroclawInstaller,
}


def get_installer(name: str):
    cls = INSTALLERS.get(name.lower())
    if cls is None:
        available = ", ".join(sorted(INSTALLERS))
        raise ValueError(f"Unknown package '{name}'. Available: {available}")
    return cls()
