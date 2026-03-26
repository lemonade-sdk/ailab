"""Installer registry for ai-dev-box."""

from .openclaw import OpenclawInstaller

INSTALLERS: dict[str, type] = {
    "openclaw": OpenclawInstaller,
}


def get_installer(name: str):
    cls = INSTALLERS.get(name.lower())
    if cls is None:
        available = ", ".join(sorted(INSTALLERS))
        raise ValueError(f"Unknown package '{name}'. Available: {available}")
    return cls()
