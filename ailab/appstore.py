"""Client for the Nimbus App Store catalog.

Fetches https://github.com/kenvandine/nimbus-app-store's catalog.json, which
lists classic-confinement snaps (openclaw, nullclaw, picoclaw, hermes-agent,
odysseus, zeroclaw) along with the ports they need forwarded, their onboard
command, and an optional post-install script. ailab's installers use this
catalog instead of hand-rolling install/onboard logic per app — the same
approach the nimbus appliance's backend uses.
"""

import json
import shlex
import time
import urllib.error
import urllib.request

CATALOG_URL = "https://raw.githubusercontent.com/kenvandine/nimbus-app-store/main/catalog.json"
_CACHE_TTL = 3600  # 1 hour
_RETRY_INTERVAL = 30  # seconds between retries when initial load fails
_REQUEST_TIMEOUT = 15

_catalog: dict | None = None
_catalog_fetched_at: float = 0.0
_catalog_retry_after: float = 0.0


def _http_get(url: str, timeout: int = _REQUEST_TIMEOUT) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (fixed https URL)
        return resp.read()


def get_catalog(force: bool = False) -> dict:
    """Fetch and cache the nimbus-app-store catalog (1 hour TTL)."""
    global _catalog, _catalog_fetched_at, _catalog_retry_after
    now = time.monotonic()
    if not force:
        if _catalog is not None and now - _catalog_fetched_at < _CACHE_TTL:
            return _catalog
        if _catalog is None and now < _catalog_retry_after:
            return {"snaps": []}
    try:
        _catalog = json.loads(_http_get(CATALOG_URL))
        _catalog_fetched_at = now
        _catalog_retry_after = 0.0
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        if _catalog is not None:
            print(f"Warning: could not refresh nimbus-app-store catalog: {exc}")
        else:
            print(f"Error: could not load nimbus-app-store catalog: {exc}")
            _catalog_retry_after = now + _RETRY_INTERVAL
    return _catalog or {"snaps": []}


def get_snaps(catalog: dict) -> list[dict]:
    return catalog.get("snaps", [])


def get_snap(catalog: dict, name: str) -> dict | None:
    return next((s for s in get_snaps(catalog) if s["name"] == name), None)


def get_channel(snap: dict) -> str | None:
    """Snap Store channel to install from, or None if not store-published."""
    return snap.get("channel") or None


def get_install_flags(snap: dict) -> list[str]:
    return list(snap.get("install_flags", ["--classic"]))


def get_store_name(snap: dict) -> str:
    """Name to install by from the store (defaults to the catalog id)."""
    return snap.get("store_name") or snap["name"]


def get_service_name(snap: dict) -> str | None:
    """systemd user service name, or None if the snap has no daemon."""
    return snap.get("service_name") or None


def get_onboard_cmd(snap: dict) -> tuple[str, list[str]] | None:
    """Return (cmd, args) for the post-install onboard command, or None."""
    raw = (snap.get("onboard_cmd") or "").strip()
    if not raw:
        return None
    try:
        parts = shlex.split(raw)
    except ValueError:
        # Malformed quoting in catalog data (e.g. an unbalanced quote) —
        # fall back to whitespace splitting rather than failing the install.
        parts = raw.split()
    if not parts:
        return None
    return parts[0], parts[1:]


def get_ports(snap: dict) -> list[int]:
    return list(snap.get("ports", []))


def get_post_install_script_url(catalog: dict, snap: dict) -> str | None:
    """Full URL to the snap's post-install script, or None if it has none."""
    script = snap.get("post_install_script")
    if not script:
        return None
    base_url = (catalog.get("base_url") or "").rstrip("/")
    return f"{base_url}/{script.lstrip('/')}"


def fetch_text(url: str) -> str:
    """Download a text resource (e.g. a post-install script) from the catalog repo."""
    return _http_get(url).decode()
