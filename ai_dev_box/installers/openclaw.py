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

        # Start container if stopped
        if _container_status(cname) != "running":
            print(f"Starting container '{container_name}'...")
            _lxc("start", cname)
            _wait_for_ready(cname)

        print("Installing openclaw via npm...")
        self._npm_install(cname, uid)

        print("Adding openclaw gateway port proxy (18789)...")
        self._add_port_proxy(cname)

        print("Configuring openclaw (probing lemonade + ollama)...")
        self._run_setup(cname, uid, gid, home)

        print()
        print(f"openclaw installed in '{container_name}'.")
        print()
        print("  Start the container:  ai-dev-box run {name}".format(name=container_name))
        print("  Launch openclaw:      openclaw")
        print("  Web UI (on host):     http://localhost:18789")
        print()
        print("  Lemonade and Ollama are pre-configured via localhost proxies.")
        print("  Make sure lemonade-server or ollama is running on the host.")

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
        # Check if the device already exists (either from OUTBOUND_PROXIES or a prior install)
        if any(port == OPENCLAW_GATEWAY_PORT for _, port in OUTBOUND_PROXIES):
            return  # already in default set

        result = _lxc(
            "config", "device", "show", cname,
            capture=True, check=False,
        )
        if result.returncode == 0 and OPENCLAW_PROXY_DEVICE in result.stdout:
            return  # already added

        _lxc(
            "config", "device", "add", cname,
            OPENCLAW_PROXY_DEVICE, "proxy",
            f"listen=tcp:127.0.0.1:{OPENCLAW_GATEWAY_PORT}",
            f"connect=tcp:127.0.0.1:{OPENCLAW_GATEWAY_PORT}",
            "bind=host",
        )

    def _run_setup(self, cname: str, uid: int, gid: int, home: str):
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
            "--",
            "node", "/tmp/setup_openclaw.js",
        )
