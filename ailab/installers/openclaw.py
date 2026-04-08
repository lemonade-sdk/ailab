"""Installer for openclaw inside an ailab container."""

import importlib.resources
import secrets
from pathlib import Path

from ..container import (
    _container_name,
    _container_status,
    add_proxy_device,
    container_exec,
    get_container_user,
    has_device,
    push_file,
    start_container,
)

# Ports openclaw needs forwarded to the host browser
OPENCLAW_PORTS = [
    ("proxy-out-openclaw",  18789),  # openclaw web UI
    ("proxy-out-gradio",     7860),  # gradio
    ("proxy-out-streamlit",  8501),  # streamlit
    ("proxy-out-jupyter",    8888),  # jupyter
    ("proxy-out-prometheus", 9090),  # prometheus / general
]
OPENCLAW_GATEWAY_PORT = 18789
OPENCLAW_PROXY_DEVICE = "proxy-out-openclaw"


class OpenclawInstaller:
    name = "openclaw"
    description = "AI coding agent with local-first LLM support (lemonade/ollama)"
    onboard_cmd = "openclaw onboard"

    def install(self, container_name: str):
        """Install and configure openclaw in the named container."""
        cname = _container_name(container_name)
        username, uid, gid, home = get_container_user(cname)

        if _container_status(cname) == "missing":
            raise RuntimeError(
                f"Container '{container_name}' not found. "
                f"Create it first with: ailab new {container_name}"
            )

        if _container_status(cname) != "running":
            print(f"Starting container '{container_name}'...")
            start_container(cname)

        print("Installing openclaw via npm...")
        self._npm_install(cname, uid)

        print("Installing openclaw gateway user service...")
        self._install_gateway_service(cname, uid, gid, home)

        print("Adding openclaw gateway port proxy (18789)...")
        self._add_port_proxy(cname)

        self._write_onboard_wrapper(cname, home)
        self._install_shell_completion(cname, uid, gid, home)

        print("Configuring openclaw (probing downloaded lemonade models via /api/v1/models)...")
        self._run_setup(cname, uid, gid, home)

        print("Pairing openclaw gateway device (generating access token)...")
        gateway_token = self._generate_gateway_token(uid)
        self._configure_gateway_env(cname, uid, gid, home, gateway_token)
        self._run_onboard(cname, uid, gid, home, gateway_token)
        # Re-patch after onboard in case openclaw rewrote openclaw.json
        self._patch_gateway_token_in_json(cname, uid, gid, home, gateway_token)

        print()
        print(f"openclaw installed in '{container_name}'.")
        print()
        print(f"  Config:       {home}/.openclaw/openclaw.json")
        print(f"  Start:        ailab run {container_name}")
        print("  Launch:       openclaw")
        print(f"  Web UI:       http://localhost:18789/#token={gateway_token}")
        print()
        print("  Lemonade is pre-configured via localhost proxy (port 13305 or 8000).")
        print("  Port 13305 is used for lemonade >= 10.1; port 8000 for older versions.")
        print("  Make sure lemonade-server is running on the host.")

    def _install_gateway_service(self, cname: str, uid: int, gid: int, home: str):
        """Install openclaw's gateway as a user-level systemd service (unit only; do not enable yet)."""
        container_exec(
            cname,
            ["bash", "-c", "openclaw gateway install 2>&1 || true"],
            uid=uid, gid=gid,
            env={"HOME": home},
            check=False,
        )
        # Only reload — do NOT enable/start yet.  The service needs the ailab
        # drop-in (with OPENCLAW_GATEWAY_TOKEN) before it first runs.
        container_exec(
            cname,
            ["bash", "-c", "systemctl --user daemon-reload 2>/dev/null || true"],
            uid=uid, gid=gid,
            env={
                "HOME": home,
                "XDG_RUNTIME_DIR": f"/run/user/{uid}",
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
            },
            check=False,
        )

    def _generate_gateway_token(self, uid: int) -> str:
        """Generate a random gateway shared token for the openclaw gateway."""
        return secrets.token_urlsafe(32)

    def _patch_gateway_token_in_json(
        self, cname: str, uid: int, gid: int, home: str, gateway_token: str
    ):
        """Patch gateway.auth.token into openclaw.json (run as container user).

        openclaw onboard may rewrite openclaw.json without preserving the token
        field; call this after onboard to ensure it's always set.
        """
        patch_py = (
            "import json, os\n"
            "p = os.path.join(os.environ['HOME'], '.openclaw', 'openclaw.json')\n"
            "try:\n"
            "    d = json.loads(open(p).read())\n"
            "except Exception:\n"
            "    d = {}\n"
            f"d.setdefault('gateway', {{}}).setdefault('auth', {{}})['token'] = '{gateway_token}'\n"
            "open(p, 'w').write(json.dumps(d, indent=2) + '\\n')\n"
        )
        container_exec(
            cname,
            ["python3"],
            uid=uid, gid=gid,
            stdin=patch_py.encode(),
            env={"HOME": home},
            check=False,
        )

    def _restart_gateway(self, cname: str, uid: int, gid: int, home: str):
        """Restart the openclaw-gateway systemd service inside the container."""
        container_exec(
            cname,
            ["bash", "-c",
             "systemctl --user daemon-reload 2>/dev/null || true"
             " && systemctl --user restart openclaw-gateway 2>/dev/null || true"],
            uid=uid, gid=gid,
            env={
                "HOME": home,
                "XDG_RUNTIME_DIR": f"/run/user/{uid}",
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
            },
            check=False,
        )

    def _configure_gateway_env(
        self, cname: str, uid: int, gid: int, home: str, gateway_token: str
    ):
        """Write gateway env vars to environment.d and a systemd service drop-in.

        The drop-in ensures the gateway service always starts with the correct
        token, regardless of how the user session was started.
        """
        env_dir = Path(home) / ".config" / "environment.d"
        conf = f"OPENCLAW_GATEWAY_TOKEN={gateway_token}\n"
        # Write environment.d for CLI / login-shell use
        container_exec(
            cname,
            ["bash", "-c", f"mkdir -p {env_dir} && cat > {env_dir}/ailab-openclaw.conf"],
            uid=uid, gid=gid,
            env={"HOME": home},
            stdin=conf.encode(),
        )
        # Write a systemd service drop-in so the daemon always has the token,
        # even in a lingering session where environment.d may not be sourced.
        dropin_dir = Path(home) / ".config" / "systemd" / "user" / "openclaw-gateway.service.d"
        dropin = (
            "[Service]\n"
            f"Environment=OPENCLAW_GATEWAY_TOKEN={gateway_token}\n"
        )
        container_exec(
            cname,
            ["bash", "-c", f"mkdir -p {dropin_dir} && cat > {dropin_dir}/ailab.conf"],
            uid=uid, gid=gid,
            env={"HOME": home},
            stdin=dropin.encode(),
        )
        # Also add OPENCLAW_GATEWAY_TOKEN to the login profile for CLI use
        snippet = f"\nexport OPENCLAW_GATEWAY_TOKEN={gateway_token}\n"
        container_exec(
            cname,
            ["bash", "-c", "cat >> /etc/profile.d/ailab-openclaw.sh"],
            stdin=snippet.encode(),
        )
        # Patch gateway.auth.token into openclaw.json so openclaw itself can read
        # the token.  openclaw onboard may rewrite this file, so we re-patch after
        # onboard as well (_patch_gateway_token_in_json).
        self._patch_gateway_token_in_json(cname, uid, gid, home, gateway_token)

        # Now enable the service (drop-in is in place, safe to start)
        container_exec(
            cname,
            ["bash", "-c",
             "systemctl --user daemon-reload 2>/dev/null || true"
             " && systemctl --user enable openclaw-gateway 2>/dev/null || true"],
            uid=uid, gid=gid,
            env={
                "HOME": home,
                "XDG_RUNTIME_DIR": f"/run/user/{uid}",
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
            },
            check=False,
        )

    def _run_onboard(
        self, cname: str, uid: int, gid: int, home: str, gateway_token: str
    ):
        """Start the gateway, pair the CLI device, then let systemd manage the service."""
        env = {
            "HOME": home,
            "XDG_RUNTIME_DIR": f"/run/user/{uid}",
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
            "OPENCLAW_GATEWAY_TOKEN": gateway_token,
        }

        # Start gateway in background, run onboard, then let systemd take over — all in one shell
        # so the background gateway process is definitely alive when onboard runs.
        script = f"""
# Stop any already-running gateway (systemd or manual) before the temporary onboard instance
systemctl --user stop openclaw-gateway 2>/dev/null || true
openclaw gateway stop 2>/dev/null || true
sleep 1

# Start gateway with explicit token (avoid config-vs-env ambiguity)
openclaw gateway run --port {OPENCLAW_GATEWAY_PORT} \
    --token {gateway_token} \
    --allow-unconfigured > /tmp/ailab-gw-onboard.log 2>&1 &
GWAY_PID=$!

# Wait up to 15s for the gateway to become ready
for i in $(seq 1 15); do
    if curl -fsS --max-time 1 http://127.0.0.1:{OPENCLAW_GATEWAY_PORT}/health >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Pair the CLI device
openclaw onboard \
    --non-interactive --accept-risk \
    --mode local --auth-choice skip \
    --gateway-auth token --gateway-token {gateway_token} \
    --gateway-bind loopback --gateway-port {OPENCLAW_GATEWAY_PORT} \
    --skip-daemon --skip-channels --skip-search --skip-skills --skip-ui 2>&1
ONBOARD_EXIT=$?
if [ $ONBOARD_EXIT -ne 0 ]; then
    echo "Warning: openclaw onboard exited with code $ONBOARD_EXIT (gateway log follows)"
    cat /tmp/ailab-gw-onboard.log || true
fi

# Stop the temporary gateway
kill $GWAY_PID 2>/dev/null || true
sleep 1

# Start the persistent systemd-managed service
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user start openclaw-gateway 2>/dev/null || true
"""
        container_exec(
            cname,
            ["bash", "-c", script],
            uid=uid, gid=gid,
            env=env,
            check=False,
        )

    def _read_device_token(self, device_auth_path: Path) -> str | None:
        """Read the operator token from device-auth.json if it exists."""
        try:
            data = json.loads(device_auth_path.read_text())
            return data.get("tokens", {}).get("operator", {}).get("token")
        except Exception:
            return None

    def _write_onboard_wrapper(self, cname: str, home: str):
        """Append a shell function that skips provider re-selection when a config exists."""
        snippet = f"""
# ailab: skip provider re-selection when config exists (mirrors ubuclaw).
# Gateway service is pre-installed as root by ailab installer.
openclaw() {{
  if [ "${{1:-}}" = "onboard" ] && [ -f "{home}/.openclaw/openclaw.json" ]; then
    shift
    command openclaw onboard --auth-choice skip "$@"
  else
    command openclaw "$@"
  fi
}}
"""
        container_exec(
            cname,
            ["bash", "-c", "cat >> /etc/profile.d/ailab-openclaw.sh"],
            stdin=snippet.encode(),
        )

    def _install_shell_completion(self, cname: str, uid: int, gid: int, home: str):
        """Install openclaw bash completion system-wide in the container."""
        exit_code, stdout, _ = container_exec(
            cname,
            ["bash", "-lc", "openclaw completion --shell bash"],
            uid=uid, gid=gid,
            env={"HOME": home},
            check=False,
        )
        if exit_code != 0 or not stdout.strip():
            print("  Warning: openclaw shell completion generation failed (non-fatal)")
            return
        container_exec(
            cname,
            ["bash", "-c", "cat > /etc/bash_completion.d/openclaw"],
            stdin=stdout.encode(),
        )

    def _npm_install(self, cname: str, uid: int):
        """Install openclaw globally via npm inside the container (as root)."""
        container_exec(
            cname,
            ["npm", "install", "-g", "openclaw"],
            env={"HOME": "/root"},
        )

    def _add_port_proxy(self, cname: str):
        """Add outbound proxies for all ports openclaw uses."""
        for device_name, port in OPENCLAW_PORTS:
            if not has_device(cname, device_name):
                ok = add_proxy_device(
                    cname, device_name,
                    f"tcp:127.0.0.1:{port}",
                    f"tcp:127.0.0.1:{port}",
                    bind="host",
                )
                if not ok:
                    if port == OPENCLAW_GATEWAY_PORT:
                        print(
                            f"  Warning: port {port} is already in use on the host "
                            f"(another openclaw gateway may be running). "
                            f"The 'Open openclaw' button will not appear until port {port} "
                            f"is free and the proxy device is added. "
                            f"Stop the conflicting process and re-run: "
                            f"ailab install <container> openclaw"
                        )
                    else:
                        print(f"  Warning: port {port} already in use on host, skipping proxy device '{device_name}'")

    def _run_setup(self, cname: str, uid: int, gid: int, home: str):
        """Push and run the Node.js setup script inside the container."""
        with importlib.resources.files("ailab.scripts").joinpath("setup_openclaw.js").open("rb") as f:
            script_content = f.read()

        push_file(cname, "/tmp/setup_openclaw.js", script_content)

        container_exec(
            cname,
            ["node", "/tmp/setup_openclaw.js"],
            uid=uid, gid=gid,
            env={"HOME": home},
        )
