"""Installer for picoclaw inside an ai-dev-box container."""

import importlib.resources
import os
import tempfile

from ..container import (
    _container_name,
    _container_status,
    _current_user,
    _lxc,
    _wait_for_ready,
    container_config_dir,
    set_container_env,
    OUTBOUND_PROXIES,
)

# picoclaw WebUI launcher port
PICOCLAW_WEBUI_PORT = 18800
PICOCLAW_PROXY_DEVICE = "proxy-out-picoclaw"


class PicoClawInstaller:
    name = "picoclaw"
    description = "Ultra-lightweight Go-based AI agent gateway (local-first, 30+ providers)"

    def install(self, container_name: str):
        cname = _container_name(container_name)
        username, uid, gid, home = _current_user()

        if _container_status(cname) == "missing":
            raise RuntimeError(
                f"Container '{container_name}' not found. "
                f"Create it first with: ai-dev-box new {container_name}"
            )

        if _container_status(cname) != "running":
            print(f"Starting container '{container_name}'...")
            _lxc("start", cname)
            _wait_for_ready(cname)

        cfg_dir = container_config_dir(container_name, home) / "picoclaw"
        cfg_dir.mkdir(parents=True, exist_ok=True)

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
        print(f"  Start:    ai-dev-box run {container_name}")
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
  x86_64)  GOARCH="amd64" ;;
  aarch64) GOARCH="arm64" ;;
  armv7l)  GOARCH="arm" ;;
  *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

# Fetch latest release metadata
RELEASE_JSON=$(curl -sf --connect-timeout 10 \
  "https://api.github.com/repos/sipeed/picoclaw/releases/latest")

VERSION=$(printf '%s' "$RELEASE_JSON" | grep '"tag_name"' | head -1 \
  | sed 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')

if [ -z "$VERSION" ]; then
  echo "ai-dev-box: could not determine picoclaw release version" >&2
  exit 1
fi

echo "ai-dev-box: picoclaw version ${VERSION}, arch ${GOARCH}"

# Try common binary naming conventions for Go projects
install_bin() {
  local url="$1" dest="$2"
  if curl -fsSL --connect-timeout 10 "$url" -o "$dest" 2>/dev/null; then
    chmod +x "$dest"
    echo "ai-dev-box: installed from ${url}"
    return 0
  fi
  return 1
}

INSTALLED=0
for NAME in \
    "picoclaw-linux-${GOARCH}" \
    "picoclaw_linux_${GOARCH}" \
    "picoclaw-linux-${GOARCH}.bin"; do
  URL="https://github.com/sipeed/picoclaw/releases/download/${VERSION}/${NAME}"
  if install_bin "$URL" /usr/local/bin/picoclaw; then
    INSTALLED=1
    break
  fi
done

# Try tar.gz variants
if [ "$INSTALLED" -eq 0 ]; then
  for NAME in \
      "picoclaw-linux-${GOARCH}.tar.gz" \
      "picoclaw_linux_${GOARCH}.tar.gz"; do
    URL="https://github.com/sipeed/picoclaw/releases/download/${VERSION}/${NAME}"
    TMP=$(mktemp -d)
    if curl -fsSL --connect-timeout 10 "$URL" | tar -xz -C "$TMP" 2>/dev/null; then
      BIN=$(find "$TMP" -name 'picoclaw' -type f | head -1)
      if [ -n "$BIN" ]; then
        install -m 755 "$BIN" /usr/local/bin/picoclaw
        rm -rf "$TMP"
        INSTALLED=1
        echo "ai-dev-box: installed from ${URL}"
        break
      fi
    fi
    rm -rf "$TMP"
  done
fi

if [ "$INSTALLED" -eq 0 ]; then
  echo "ai-dev-box: binary download failed — trying go install..." >&2
  if command -v go >/dev/null 2>&1; then
    GOPATH=$(mktemp -d)
    GOPATH="$GOPATH" go install github.com/sipeed/picoclaw@latest
    install -m 755 "$GOPATH/bin/picoclaw" /usr/local/bin/picoclaw
    rm -rf "$GOPATH"
  else
    echo "ai-dev-box: go not available; install Go then: go install github.com/sipeed/picoclaw@latest" >&2
    exit 1
  fi
fi

echo "ai-dev-box: picoclaw installed at /usr/local/bin/picoclaw"

# picoclaw-launcher is a separate binary in some releases; symlink if missing
if ! command -v picoclaw-launcher >/dev/null 2>&1; then
  ln -sf /usr/local/bin/picoclaw /usr/local/bin/picoclaw-launcher 2>/dev/null || true
fi
"""
        _lxc("exec", cname, "--", "bash", "-c", install_script)

    def _add_port_proxy(self, cname: str):
        if any(port == PICOCLAW_WEBUI_PORT for _, port in OUTBOUND_PROXIES):
            return

        # Check if already added by a prior install
        result = _lxc("config", "device", "show", cname, capture=True, check=False)
        if result.returncode == 0 and PICOCLAW_PROXY_DEVICE in result.stdout:
            return

        _lxc(
            "config", "device", "add", cname,
            PICOCLAW_PROXY_DEVICE, "proxy",
            f"listen=tcp:127.0.0.1:{PICOCLAW_WEBUI_PORT}",
            f"connect=tcp:127.0.0.1:{PICOCLAW_WEBUI_PORT}",
            "bind=host",
        )

    def _run_setup(self, cname: str, uid: int, gid: int, home: str, cfg_dir):
        with importlib.resources.files("ai_dev_box.scripts").joinpath("setup_picoclaw.py").open("rb") as f:
            script_content = f.read()

        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
            tmp.write(script_content)
            tmp_path = tmp.name

        try:
            _lxc("file", "push", tmp_path, f"{cname}/tmp/setup_picoclaw.py")
        finally:
            os.unlink(tmp_path)

        _lxc(
            "exec", cname,
            f"--user={uid}",
            f"--group={gid}",
            f"--env=HOME={home}",
            f"--env=PICOCLAW_CONFIG_DIR={cfg_dir}",
            "--",
            "python3", "/tmp/setup_picoclaw.py",
        )
