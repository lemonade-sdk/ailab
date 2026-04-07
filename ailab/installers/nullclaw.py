"""Installer for nullclaw inside an ailab container."""

import importlib.resources

from ..container import (
    _container_name,
    _container_status,
    _current_user,
    _wait_for_ready,
    add_proxy_device,
    container_config_dir,
    container_exec,
    push_file,
    set_container_env,
    start_container,
)

# nullclaw gateway port
NULLCLAW_GATEWAY_PORT = 3000


class NullclawInstaller:
    name = "nullclaw"
    description = "Lightweight static-binary AI agent gateway (local-first, Zig-built)"
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

        cfg_dir = container_config_dir(container_name, home) / "nullclaw"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        container_exec(cname, ["chown", "-R", f"{uid}:{gid}", str(cfg_dir)])

        print("Installing nullclaw (downloading binary from GitHub releases)...")
        self._install_binary(cname, uid)

        print(f"Adding nullclaw gateway port proxy ({NULLCLAW_GATEWAY_PORT})...")
        self._add_port_proxy(cname)

        print("Setting nullclaw config env vars...")
        set_container_env(cname, {"NULLCLAW_CONFIG_DIR": str(cfg_dir)},
                          profile_name="nullclaw")

        print("Configuring nullclaw (probing lemonade + ollama)...")
        self._run_setup(cname, uid, gid, home, cfg_dir)

        print()
        print(f"nullclaw installed in '{container_name}'.")
        print()
        print(f"  Config:   {cfg_dir}/config.json")
        print(f"  Start:    ailab run {container_name}")
        print("  Gateway:  nullclaw gateway")
        print("  Chat:     nullclaw agent")
        print(f"  Web UI:   http://localhost:{NULLCLAW_GATEWAY_PORT}")
        print()
        print("  Lemonade and Ollama are pre-configured via localhost proxies.")
        print("  Make sure lemonade-server or ollama is running on the host.")

    def _install_binary(self, cname: str, uid: int):
        """Download nullclaw static binary from GitHub releases."""
        install_script = r"""
set -eu
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  NCARCH="x86_64" ;;
  aarch64) NCARCH="aarch64" ;;
  armv7l)  NCARCH="arm32-gnu" ;;
  riscv64) NCARCH="riscv64" ;;
  *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

VERSION=$(curl -sf --connect-timeout 10 \
  "https://api.github.com/repos/nullclaw/nullclaw/releases/latest" \
  | grep '"tag_name"' | head -1 \
  | sed 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')

if [ -z "$VERSION" ]; then
  echo "ailab: could not determine nullclaw release version" >&2
  exit 1
fi

BINARY="nullclaw-linux-${NCARCH}.bin"
echo "ailab: downloading nullclaw ${VERSION} (${BINARY})..."
curl -fsSL \
  "https://github.com/nullclaw/nullclaw/releases/download/${VERSION}/${BINARY}" \
  -o /usr/local/bin/nullclaw
chmod +x /usr/local/bin/nullclaw
echo "ailab: nullclaw installed at /usr/local/bin/nullclaw"
"""
        container_exec(cname, ["bash", "-c", install_script])

    def _add_port_proxy(self, cname: str):
        add_proxy_device(
            cname, "proxy-out-nullclaw",
            f"tcp:127.0.0.1:{NULLCLAW_GATEWAY_PORT}",
            f"tcp:127.0.0.1:{NULLCLAW_GATEWAY_PORT}",
            bind="host",
        )

    def _run_setup(self, cname: str, uid: int, gid: int, home: str, cfg_dir):
        with importlib.resources.files("ailab.scripts").joinpath("setup_nullclaw.sh").open("rb") as f:
            script_content = f.read()

        push_file(cname, "/tmp/setup_nullclaw.sh", script_content)

        container_exec(
            cname,
            ["sh", "/tmp/setup_nullclaw.sh"],
            uid=uid, gid=gid,
            env={"HOME": home, "NULLCLAW_CONFIG_DIR": str(cfg_dir)},
        )
