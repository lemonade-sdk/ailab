"""Installer for openclaw inside an ailab container."""

import importlib.resources

from ..container import (
    _container_name,
    _container_status,
    _current_user,
    _lxc,
    _wait_for_ready,
    container_config_dir,
    push_file,
    set_container_env,
    OUTBOUND_PROXIES,
)

# openclaw gateway port — web UI accessible from host browser
OPENCLAW_GATEWAY_PORT = 18789
OPENCLAW_PROXY_DEVICE = "proxy-out-openclaw"


class OpenclawInstaller:
    name = "openclaw"
    description = "AI coding agent with local-first LLM support (lemonade/ollama)"
    onboard_cmd = "openclaw onboard"

    def install(self, container_name: str):
        """Install and configure openclaw in the named container."""
        cname = _container_name(container_name)
        username, uid, gid, home = _current_user()

        if _container_status(cname) == "missing":
            raise RuntimeError(
                f"Container '{container_name}' not found. "
                f"Create it first with: ailab new {container_name}"
            )

        if _container_status(cname) != "running":
            print(f"Starting container '{container_name}'...")
            _lxc("start", cname)
            _wait_for_ready(cname)

        # Per-container config dir (inside the bind-mounted home, so no extra mount)
        cfg_dir = container_config_dir(container_name, home) / "openclaw"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        # Ensure correct ownership in case of re-install (previous run may have
        # written files as container root, which maps to a different host UID).
        _lxc("exec", cname, "--",
             "chown", "-R", f"{uid}:{gid}", str(cfg_dir))

        print("Installing openclaw via npm...")
        self._npm_install(cname, uid)

        print("Installing openclaw gateway system service (as root)...")
        self._install_gateway_service(cname)

        print("Adding openclaw gateway port proxy (18789)...")
        self._add_port_proxy(cname)

        print("Setting openclaw config env vars...")
        env = {
            "OPENCLAW_STATE_DIR":   str(cfg_dir),
            "OPENCLAW_CONFIG_PATH": str(cfg_dir / "openclaw.json"),
        }
        set_container_env(cname, env, profile_name="openclaw")
        self._write_onboard_wrapper(cname, cfg_dir)
        self._install_shell_completion(cname, uid, gid, home, cfg_dir)

        print("Configuring openclaw (probing lemonade via Ollama API)...")
        self._run_setup(cname, uid, gid, home, cfg_dir)

        print()
        print(f"openclaw installed in '{container_name}'.")
        print()
        print(f"  Config:       {cfg_dir}/openclaw.json")
        print(f"  Start:        ailab run {container_name}")
        print("  Launch:       openclaw")
        print("  Web UI:       http://localhost:18789")
        print()
        print("  Lemonade is pre-configured via localhost proxy (port 8000).")
        print("  Make sure lemonade-server is running on the host.")

    def _install_gateway_service(self, cname: str):
        """Install openclaw's gateway as a system service (requires root).

        openclaw onboard tries to do this itself but fails in LXD containers
        because non-root users can't connect to the system D-Bus.  Running it
        here as root pre-empts that failure.
        """
        _lxc(
            "exec", cname,
            "--env=HOME=/root",
            "--",
            "bash", "-c",
            "openclaw gateway install 2>&1 || true",
        )
        # Reload and enable regardless — openclaw gateway install may have
        # written the unit file without reloading.
        _lxc("exec", cname, "--",
             "bash", "-c",
             "systemctl daemon-reload 2>/dev/null || true"
             " && systemctl enable openclaw-gateway 2>/dev/null || true"
             " && systemctl start openclaw-gateway 2>/dev/null || true")

    def _write_onboard_wrapper(self, cname: str, cfg_dir):
        """Append a shell function that mirrors the ubuclaw launcher behaviour:
        skip provider selection during 'openclaw onboard' when a config already exists."""
        config_file = cfg_dir / "openclaw.json"
        snippet = f"""
# ailab: skip provider re-selection when config exists (mirrors ubuclaw).
# Gateway service is pre-installed as root by ailab installer.
openclaw() {{
  if [ "${{1:-}}" = "onboard" ] && [ -f "{config_file}" ]; then
    shift
    command openclaw onboard --auth-choice skip "$@"
  else
    command openclaw "$@"
  fi
}}
"""
        _lxc("exec", cname, "--",
             "bash", "-c",
             "cat >> /etc/profile.d/ailab-openclaw.sh",
             input=snippet)

    def _install_shell_completion(self, cname: str, uid: int, gid: int, home: str, cfg_dir):
        """Install openclaw bash completion for the container user."""
        result = _lxc(
            "exec", cname,
            f"--user={uid}",
            f"--group={gid}",
            f"--env=HOME={home}",
            f"--env=OPENCLAW_STATE_DIR={cfg_dir}",
            f"--env=OPENCLAW_CONFIG_PATH={cfg_dir}/openclaw.json",
            "--",
            "bash", "-lc",
            "openclaw completion --shell bash --install --yes",
            check=False,
            capture=True,
        )
        if result.returncode != 0:
            print("  Warning: openclaw shell completion install failed (non-fatal)")

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
        with importlib.resources.files("ailab.scripts").joinpath("setup_openclaw.js").open("rb") as f:
            script_content = f.read()

        push_file(cname, "/tmp/setup_openclaw.js", script_content)

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
