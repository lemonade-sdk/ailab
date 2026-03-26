"""Installer registry for ailab."""

from .nullclaw import NullclawInstaller
from .openclaw import OpenclawInstaller
from .picoclaw import PicoClawInstaller

INSTALLERS: dict[str, type] = {
    "nullclaw": NullclawInstaller,
    "openclaw": OpenclawInstaller,
    "picoclaw": PicoClawInstaller,
}


def get_installer(name: str):
    cls = INSTALLERS.get(name.lower())
    if cls is None:
        available = ", ".join(sorted(INSTALLERS))
        raise ValueError(f"Unknown package '{name}'. Available: {available}")
    return cls()
