"""Installer for openclaw inside an ai-dev-box container."""

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

# openclaw gateway port — web UI accessible from host browser
OPENCLAW_GATEWAY_PORT = 18789
OPENCLAW_PROXY_DEVICE = "proxy-out-openclaw"


class OpenclawInstaller:
    name = "openclaw"
    description = "AI coding agent with local-first LLM support (lemonade/ollama)"

    def install(self, container_name: str):
        """Install and configure openclaw in the named container."""
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

        # Per-container config dir (inside the bind-mounted home, so no extra mount)
        cfg_dir = container_config_dir(container_name, home) / "openclaw"
        cfg_dir.mkdir(parents=True, exist_ok=True)

        print("Installing openclaw via npm...")
        self._npm_install(cname, uid)

        print("Adding openclaw gateway port proxy (18789)...")
        self._add_port_proxy(cname)

        print("Setting openclaw config env vars...")
        env = {
            "OPENCLAW_STATE_DIR":   str(cfg_dir),
            "OPENCLAW_CONFIG_PATH": str(cfg_dir / "openclaw.json"),
        }
        set_container_env(cname, env)

        print("Configuring openclaw (probing lemonade via Ollama API)...")
        self._run_setup(cname, uid, gid, home, cfg_dir)

        print()
        print(f"openclaw installed in '{container_name}'.")
        print()
        print(f"  Config:       {cfg_dir}/openclaw.json")
        print(f"  Start:        ai-dev-box run {container_name}")
        print("  Launch:       openclaw")
        print("  Web UI:       http://localhost:18789")
        print()
        print("  Lemonade is pre-configured via localhost proxy (port 8000).")
        print("  Make sure lemonade-server is running on the host.")

    def _npm_install(self, cname: str, uid: int):
        """Install openclaw globally via npm inside the container (as root)."""
        _lxc(
            "exec", cname,
            "--env=HOME=/root",
            "--",
            "npm", "install", "-g", "openclaw",
        )

    def _add_port_proxy(self, cname: str):
        """Add outbound proxy for openclaw's gateway port if not already present."""
        if any(port == OPENCLAW_GATEWAY_PORT for _, port in OUTBOUND_PROXIES):
            return

        result = _lxc("config", "device", "show", cname, capture=True, check=False)
        if result.returncode == 0 and OPENCLAW_PROXY_DEVICE in result.stdout:
            return

        _lxc(
            "config", "device", "add", cname,
            OPENCLAW_PROXY_DEVICE, "proxy",
            f"listen=tcp:127.0.0.1:{OPENCLAW_GATEWAY_PORT}",
            f"connect=tcp:127.0.0.1:{OPENCLAW_GATEWAY_PORT}",
            "bind=host",
        )

    def _run_setup(self, cname: str, uid: int, gid: int, home: str, cfg_dir):
        """Push and run the Node.js setup script inside the container."""
        with importlib.resources.files("ai_dev_box.scripts").joinpath("setup_openclaw.js").open("rb") as f:
            script_content = f.read()

        with tempfile.NamedTemporaryFile(suffix=".js", delete=False) as tmp:
            tmp.write(script_content)
            tmp_path = tmp.name

        try:
            _lxc("file", "push", tmp_path, f"{cname}/tmp/setup_openclaw.js")
        finally:
            os.unlink(tmp_path)

        _lxc(
            "exec", cname,
            f"--user={uid}",
            f"--group={gid}",
            f"--env=HOME={home}",
            f"--env=OPENCLAW_STATE_DIR={cfg_dir}",
            f"--env=OPENCLAW_CONFIG_PATH={cfg_dir}/openclaw.json",
            "--",
            "node", "/tmp/setup_openclaw.js",
        )
