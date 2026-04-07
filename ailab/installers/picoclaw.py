"""Installer for picoclaw inside an ailab container."""

import importlib.resources

from ..container import (
    _container_name,
    _container_status,
    _current_user,
    _wait_for_ready,
    add_proxy_device,
    container_config_dir,
    container_exec,
    has_device,
    push_file,
    set_container_env,
    start_container,
    OUTBOUND_PROXIES,
)

# picoclaw WebUI launcher port
PICOCLAW_WEBUI_PORT = 18800
PICOCLAW_PROXY_DEVICE = "proxy-out-picoclaw"


class PicoClawInstaller:
    name = "picoclaw"
    description = "Ultra-lightweight Go-based AI agent gateway (local-first, 30+ providers)"
    onboard_cmd = None

    def install(self, container_name: str):
        cname = _container_name(container_name)
        username, uid, gid, home = _current_user()

        if _container_status(cname) == "missing":
            raise RuntimeError(
                f"Container '{container_name}' not found. "
                f"Create it first with: ailab new {container_name}"
            )

        if _container_status(cname) != "running":
            print(f"Starting container '{container_name}'...")
            start_container(cname)

        cfg_dir = container_config_dir(container_name, home) / "picoclaw"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        container_exec(cname, ["chown", "-R", f"{uid}:{gid}", str(cfg_dir)])

        print("Installing picoclaw (downloading binary from GitHub releases)...")
        self._install_binary(cname, uid)

        print(f"Adding picoclaw WebUI port proxy ({PICOCLAW_WEBUI_PORT})...")
        self._add_port_proxy(cname)

        print("Setting picoclaw config env vars...")
        set_container_env(cname, {"PICOCLAW_CONFIG_DIR": str(cfg_dir)},
                          profile_name="picoclaw")

        print("Configuring picoclaw (probing lemonade + ollama)...")
        self._run_setup(cname, uid, gid, home, cfg_dir)

        print()
        print(f"picoclaw installed in '{container_name}'.")
        print()
        print(f"  Config:   {cfg_dir}/config.json")
        print(f"  Start:    ailab run {container_name}")
        print("  WebUI:    picoclaw-launcher")
        print("  Chat:     picoclaw agent")
        print(f"  Web UI:   http://localhost:{PICOCLAW_WEBUI_PORT}")
        print()
        print("  Lemonade and Ollama are pre-configured via localhost proxies.")
        print("  Make sure lemonade-server or ollama is running on the host.")

    def _install_binary(self, cname: str, uid: int):
        """Download picoclaw binary from GitHub releases (sipeed/picoclaw)."""
        install_script = r"""
set -eu
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  PICOARCH="x86_64" ;;
  aarch64) PICOARCH="arm64" ;;
  armv7l)  PICOARCH="armv7" ;;
  armv6l)  PICOARCH="armv6" ;;
  *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

# Fetch latest release metadata
RELEASE_JSON=$(curl -sf --connect-timeout 10 \
  "https://api.github.com/repos/sipeed/picoclaw/releases/latest")

VERSION=$(printf '%s' "$RELEASE_JSON" | grep '"tag_name"' | head -1 \
  | sed 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')

if [ -z "$VERSION" ]; then
  echo "ailab: could not determine picoclaw release version" >&2
  exit 1
fi

echo "ailab: picoclaw version ${VERSION}, arch ${PICOARCH}"

find_release_asset_url() {
  local asset_name="$1"
  printf '%s' "$RELEASE_JSON" \
    | grep "\"browser_download_url\": \".*/${asset_name}\"" \
    | head -1 \
    | sed 's/.*"browser_download_url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/'
}

install_from_archive() {
  local url="$1" tmp archive bin
  tmp=$(mktemp -d)
  archive="$tmp/picoclaw.tar.gz"
  if curl -fsSL --connect-timeout 10 "$url" -o "$archive" 2>/dev/null \
      && tar -xzf "$archive" -C "$tmp" 2>/dev/null; then
    bin=$(find "$tmp" -name 'picoclaw' -type f | head -1)
    if [ -n "$bin" ]; then
      install -m 755 "$bin" /usr/local/bin/picoclaw
      rm -rf "$tmp"
      echo "ailab: installed from ${url}"
      return 0
    fi
  fi
  rm -rf "$tmp"
  return 1
}

INSTALLED=0
ARCHIVE_NAME="picoclaw_Linux_${PICOARCH}.tar.gz"
URL=$(find_release_asset_url "$ARCHIVE_NAME")
if [ -n "${URL:-}" ] && install_from_archive "$URL"; then
  INSTALLED=1
fi

# Fallback to direct release URL if GitHub API output shape changes.
if [ "$INSTALLED" -eq 0 ]; then
  URL="https://github.com/sipeed/picoclaw/releases/download/${VERSION}/${ARCHIVE_NAME}"
  if install_from_archive "$URL"; then
    INSTALLED=1
  fi
fi

if [ "$INSTALLED" -eq 0 ]; then
  echo "ailab: binary download failed — trying go install..." >&2
  if command -v go >/dev/null 2>&1; then
    GOPATH=$(mktemp -d)
    GOPATH="$GOPATH" go install github.com/sipeed/picoclaw@latest
    install -m 755 "$GOPATH/bin/picoclaw" /usr/local/bin/picoclaw
    rm -rf "$GOPATH"
  else
    echo "ailab: go not available; install Go then: go install github.com/sipeed/picoclaw@latest" >&2
    exit 1
  fi
fi

echo "ailab: picoclaw installed at /usr/local/bin/picoclaw"

# picoclaw-launcher is a separate binary in some releases; symlink if missing
if ! command -v picoclaw-launcher >/dev/null 2>&1; then
  ln -sf /usr/local/bin/picoclaw /usr/local/bin/picoclaw-launcher 2>/dev/null || true
fi
"""
        container_exec(cname, ["bash", "-c", install_script])

    def _add_port_proxy(self, cname: str):
        if any(port == PICOCLAW_WEBUI_PORT for _, port in OUTBOUND_PROXIES):
            return
        if has_device(cname, PICOCLAW_PROXY_DEVICE):
            return
        add_proxy_device(
            cname, PICOCLAW_PROXY_DEVICE,
            f"tcp:127.0.0.1:{PICOCLAW_WEBUI_PORT}",
            f"tcp:127.0.0.1:{PICOCLAW_WEBUI_PORT}",
            bind="host",
        )

    def _run_setup(self, cname: str, uid: int, gid: int, home: str, cfg_dir):
        with importlib.resources.files("ailab.scripts").joinpath("setup_picoclaw.py").open("rb") as f:
            script_content = f.read()

        push_file(cname, "/tmp/setup_picoclaw.py", script_content)

        container_exec(
            cname,
            ["python3", "/tmp/setup_picoclaw.py"],
            uid=uid, gid=gid,
            env={"HOME": home, "PICOCLAW_CONFIG_DIR": str(cfg_dir)},
        )
