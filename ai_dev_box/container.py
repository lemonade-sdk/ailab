"""LXD container management for ai-dev-box."""

import importlib.resources
import json
import os
import pwd
import subprocess
import sys
import time
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

CONTAINER_PREFIX = "ai-dev-box-"
BASE_IMAGE = "ubuntu-daily:devel"

# Ports proxied INTO the container (container localhost → host service)
# Apps in the container connect to these as if they're local, but they reach the host.
INBOUND_PROXIES = [
    ("lemonade", 8000),   # lemonade-server
    ("ollama",   11434),  # ollama
]

# Ports proxied FROM the container to the host (host browser → container service)
# Web UIs running in the container are accessible on the host at the same port.
OUTBOUND_PROXIES = [
    ("web-3000",  3000),   # node/react dev servers
    ("web-7860",  7860),   # gradio
    ("web-8080",  8080),   # generic (openclaw, etc.)
    ("web-8888",  8888),   # jupyter
    ("web-8501",  8501),   # streamlit
    ("web-9090",  9090),   # prometheus / generic
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(args, *, check=True, capture=False, input=None):
    """Run a command, returning CompletedProcess."""
    kwargs = dict(check=check, text=True, input=input)
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    return subprocess.run(args, **kwargs)


def _lxc(*args, capture=False, check=True, input=None):
    return _run(["lxc", *args], capture=capture, check=check, input=input)


def _container_name(name: str) -> str:
    if name.startswith(CONTAINER_PREFIX):
        return name
    return f"{CONTAINER_PREFIX}{name}"


def _short_name(container_name: str) -> str:
    if container_name.startswith(CONTAINER_PREFIX):
        return container_name[len(CONTAINER_PREFIX):]
    return container_name


def _current_user():
    uid = os.getuid()
    gid = os.getgid()
    pw = pwd.getpwuid(uid)
    return pw.pw_name, uid, gid, pw.pw_dir


def container_config_dir(name: str, home: str) -> Path:
    """Per-container config directory on the host (also accessible inside the
    container at the same path, because the home dir is bind-mounted)."""
    return Path(home) / ".local" / "share" / "ai-dev-box" / "containers" / name


def push_file(cname: str, remote_path: str, content: bytes | str):
    """Write content to a file inside the container via lxc exec stdin.

    Unlike 'lxc file push', this works on tmpfs mounts (e.g. /tmp).
    """
    if isinstance(content, bytes):
        content = content.decode()
    _lxc("exec", cname, "--", "bash", "-c",
         f"rm -f {remote_path} && cat > {remote_path}", input=content)


def set_container_env(cname: str, env: dict[str, str], profile_name: str | None = None):
    """Persist environment variables in the container.

    Sets them via both LXD config (available to lxc exec calls) and a
    /etc/profile.d/ script (survives PAM re-initialization in login shells).

    profile_name: base name for the profile.d file, e.g. "openclaw" →
                  /etc/profile.d/ai-dev-box-openclaw.sh
                  Defaults to "container" if not given.
    """
    for key, value in env.items():
        _lxc("config", "set", cname, f"environment.{key}", value)

    tag = profile_name or "container"
    lines = [f"# ai-dev-box: {tag} environment (auto-generated)"]
    for key, value in env.items():
        lines.append(f'export {key}="{value}"')
    script = "\n".join(lines) + "\n"
    dest = f"/etc/profile.d/ai-dev-box-{tag}.sh"
    # Write via stdin to avoid shell quoting issues with paths
    _lxc("exec", cname, "--",
         "bash", "-c", f"cat > {dest} && chmod 644 {dest}",
         input=script)


def _container_status(cname: str) -> str:
    """Return container status string or 'missing'."""
    result = _lxc("list", cname, "--format=json", capture=True, check=False)
    if result.returncode != 0:
        return "missing"
    data = json.loads(result.stdout)
    if not data:
        return "missing"
    return data[0].get("status", "unknown").lower()


def _wait_for_network(cname: str, timeout: int = 60):
    """Wait until the container has an IPv4 address."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _lxc("list", cname, "--format=json", capture=True, check=False)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data:
                for net in data[0].get("state", {}).get("network", {}).values():
                    for addr in net.get("addresses", []):
                        if addr["family"] == "inet" and not addr["address"].startswith("127."):
                            return
        time.sleep(2)
    raise TimeoutError(f"Container {cname} did not get a network address within {timeout}s")


def _wait_for_ready(cname: str, timeout: int = 30):
    """Wait until we can exec a command in the container."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _lxc("exec", cname, "--", "true", capture=True, check=False)
        if result.returncode == 0:
            return
        time.sleep(2)
    raise TimeoutError(f"Container {cname} not ready after {timeout}s")


# ── Profile ───────────────────────────────────────────────────────────────────

def ensure_lxd_profile():
    """Create the ai-dev-box LXD profile if it doesn't exist."""
    result = _lxc("profile", "show", "ai-dev-box", capture=True, check=False)
    if result.returncode == 0:
        return  # already exists

    print("Creating LXD profile 'ai-dev-box'...")
    _lxc("profile", "create", "ai-dev-box")
    profile_yaml = """\
config:
  security.nesting: "true"
description: ai-dev-box profile
devices:
  eth0:
    name: eth0
    network: lxdbr0
    type: nic
  root:
    path: /
    pool: default
    type: disk
"""
    _lxc("profile", "edit", "ai-dev-box", input=profile_yaml)


# ── Container creation ────────────────────────────────────────────────────────

def create_container(name: str, extra_outbound_ports: list[tuple[int, int]] | None = None):
    """
    Create and fully configure a new ai-dev-box container.

    extra_outbound_ports: list of (host_port, container_port) tuples to add
                          in addition to the defaults.
    """
    cname = _container_name(name)
    username, uid, gid, home = _current_user()

    status = _container_status(cname)
    if status != "missing":
        print(f"Container '{name}' already exists (status: {status}).")
        sys.exit(1)

    ensure_lxd_profile()

    # ── Launch ────────────────────────────────────────────────────────────────
    print(f"Launching container '{cname}' from {BASE_IMAGE}...")
    _lxc("launch", BASE_IMAGE, cname, "--profile=ai-dev-box")

    # ── UID/GID passthrough so mounted homedir works ──────────────────────────
    print("Configuring UID/GID mapping...")
    idmap = f"uid {uid} {uid}\ngid {gid} {gid}"
    _lxc("config", "set", cname, "raw.idmap", idmap)

    # security.nesting allows docker/fuse inside the container
    _lxc("config", "set", cname, "security.nesting", "true")

    # ── Mount home directory ──────────────────────────────────────────────────
    print(f"Mounting home directory {home}...")
    _lxc("config", "device", "add", cname, "homedir", "disk",
         f"source={home}", f"path={home}")

    # ── Per-container config directory ────────────────────────────────────────
    # Lives inside the already-mounted home dir, so no extra mount is needed.
    cfg_dir = container_config_dir(name, home)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    set_container_env(cname, {"AI_DEV_BOX_CONFIG_DIR": str(cfg_dir)},
                      profile_name="base")

    # ── Inbound proxies: container localhost → host service ───────────────────
    print("Adding inbound port proxies (container → host services)...")
    for dev_name, port in INBOUND_PROXIES:
        _lxc("config", "device", "add", cname, f"proxy-in-{dev_name}", "proxy",
             f"listen=tcp:127.0.0.1:{port}",
             f"connect=tcp:127.0.0.1:{port}",
             "bind=container")

    # ── Outbound proxies: host → container service ────────────────────────────
    print("Adding outbound port proxies (container services → host browser)...")
    all_outbound = list(OUTBOUND_PROXIES)
    if extra_outbound_ports:
        for hp, cp in extra_outbound_ports:
            all_outbound.append((f"web-custom-{hp}", hp, cp))

    for entry in all_outbound:
        if len(entry) == 2:
            dev_name, port = entry
            host_port, container_port = port, port
        else:
            dev_name, host_port, container_port = entry

        result = _lxc("config", "device", "add", cname, f"proxy-out-{dev_name}", "proxy",
                       f"listen=tcp:127.0.0.1:{host_port}",
                       f"connect=tcp:127.0.0.1:{container_port}",
                       "bind=host", check=False)
        if result.returncode != 0:
            print(f"  Warning: skipping port {host_port} (already in use on host)")

    # ── Restart to apply idmap + devices ─────────────────────────────────────
    print("Restarting container to apply configuration...")
    _lxc("restart", cname)

    print("Waiting for container to be ready...")
    _wait_for_ready(cname)
    _wait_for_network(cname)

    # ── Run init script inside container ─────────────────────────────────────
    _run_init_script(cname, username, uid, gid, home)

    print(f"\nContainer '{name}' is ready!")
    print(f"  Run:   ai-dev-box run {name}")
    print(f"  Shell: lxc exec {cname} --user {uid} -- /bin/bash -l")


def _run_init_script(cname: str, username: str, uid: int, gid: int, home: str):
    """Push and execute the container init script."""
    print("Running container initialization (this may take a few minutes)...")

    with importlib.resources.files("ai_dev_box.scripts").joinpath("container_init.sh").open("rb") as f:
        script_content = f.read()

    push_file(cname, "/tmp/ai-dev-box-init.sh", script_content)

    _lxc("exec", cname, "--",
         "bash", "/tmp/ai-dev-box-init.sh",
         username, str(uid), str(gid), home)


# ── Port management ───────────────────────────────────────────────────────────

def add_port(name: str, host_port: int, container_port: int, direction: str = "outbound"):
    """
    Add a port proxy to a container.

    direction: 'outbound' (host → container, for web UIs)
               'inbound'  (container → host, for host services)
    """
    cname = _container_name(name)
    if _container_status(cname) == "missing":
        print(f"Container '{name}' not found.")
        sys.exit(1)

    if direction == "outbound":
        dev_name = f"proxy-out-custom-{host_port}"
        result = _lxc("config", "device", "add", cname, dev_name, "proxy",
                       f"listen=tcp:127.0.0.1:{host_port}",
                       f"connect=tcp:127.0.0.1:{container_port}",
                       "bind=host", check=False)
        if result.returncode != 0:
            print(f"Error: port {host_port} is already in use on the host.")
            sys.exit(1)
        print(f"Added outbound proxy: host:{host_port} → container:{container_port}")
    else:
        dev_name = f"proxy-in-custom-{container_port}"
        _lxc("config", "device", "add", cname, dev_name, "proxy",
             f"listen=tcp:127.0.0.1:{container_port}",
             f"connect=tcp:127.0.0.1:{host_port}",
             "bind=container")
        print(f"Added inbound proxy: container:{container_port} → host:{host_port}")


def remove_port(name: str, host_port: int, direction: str = "outbound"):
    """Remove a custom port proxy from a container."""
    cname = _container_name(name)
    if _container_status(cname) == "missing":
        print(f"Container '{name}' not found.")
        sys.exit(1)

    if direction == "outbound":
        dev_name = f"proxy-out-custom-{host_port}"
    else:
        dev_name = f"proxy-in-custom-{host_port}"

    _lxc("config", "device", "remove", cname, dev_name, check=False)
    print(f"Removed proxy device '{dev_name}'")


def list_ports(name: str):
    """List all proxy devices on a container."""
    cname = _container_name(name)
    # Use lxc list JSON output which includes expanded_devices
    result = _lxc("list", cname, "--format=json", capture=True, check=False)
    if result.returncode != 0:
        print(f"Container '{name}' not found.")
        sys.exit(1)
    data = json.loads(result.stdout)
    if not data:
        print(f"Container '{name}' not found.")
        sys.exit(1)

    devices = data[0].get("expanded_devices", {})
    proxies = {k: v for k, v in devices.items() if v.get("type") == "proxy"}
    if not proxies:
        print("No proxy devices configured.")
        return

    print(f"{'Device':<32} {'Direction':<12} {'Listen':<28} {'Connect'}")
    print("-" * 88)
    for dev_name, cfg in sorted(proxies.items()):
        bind = cfg.get("bind", "host")
        direction = "outbound" if bind == "host" else "inbound "
        listen = cfg.get("listen", "")
        connect = cfg.get("connect", "")
        print(f"{dev_name:<32} {direction:<12} {listen:<28} {connect}")


# ── Run / shell ───────────────────────────────────────────────────────────────

def run_container(name: str):
    """Start the container (if needed) and open a user shell."""
    cname = _container_name(name)
    username, uid, gid, home = _current_user()

    status = _container_status(cname)
    if status == "missing":
        print(f"Container '{name}' not found. Create it with: ai-dev-box new {name}")
        sys.exit(1)

    if status != "running":
        print(f"Starting container '{name}'...")
        _lxc("start", cname)
        _wait_for_ready(cname)

    print(f"Opening shell in '{name}' as {username}...")
    os.execvp("lxc", [
        "lxc", "exec", cname,
        f"--user={uid}",
        f"--group={gid}",
        f"--env=HOME={home}",
        f"--env=USER={username}",
        f"--env=LOGNAME={username}",
        "--env=TERM=xterm-256color",
        f"--cwd={home}",
        "--",
        "/bin/bash", "--login",
    ])


# ── List ──────────────────────────────────────────────────────────────────────

def list_containers():
    """List all ai-dev-box containers."""
    result = _lxc("list", f"{CONTAINER_PREFIX}*", "--format=json",
                  capture=True, check=False)
    if result.returncode != 0:
        print("No containers found (or LXD not available).")
        return

    containers = json.loads(result.stdout)
    if not containers:
        print("No ai-dev-box containers found.")
        print(f"Create one with: ai-dev-box new <name>")
        return

    print(f"{'NAME':<25} {'STATUS':<12} {'IPv4':<18} {'OUTBOUND PORTS'}")
    print("-" * 80)
    for c in containers:
        cname = c["name"]
        short = _short_name(cname)
        status = c.get("status", "unknown")
        ipv4 = ""
        for net in c.get("state", {}).get("network", {}).values():
            for addr in net.get("addresses", []):
                if addr["family"] == "inet" and not addr["address"].startswith("127."):
                    ipv4 = addr["address"]
                    break

        # Collect outbound proxy ports
        devices = c.get("expanded_devices", {})
        ports = []
        for dev_name, cfg in devices.items():
            if cfg.get("type") == "proxy" and cfg.get("bind", "host") == "host":
                listen = cfg.get("listen", "")
                if ":" in listen:
                    port = listen.rsplit(":", 1)[-1]
                    ports.append(port)

        ports_str = ",".join(sorted(ports, key=int)) if ports else "-"
        print(f"{short:<25} {status:<12} {ipv4:<18} {ports_str}")


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_container(name: str, force: bool = False):
    """Stop and delete a container."""
    cname = _container_name(name)
    if _container_status(cname) == "missing":
        print(f"Container '{name}' not found.")
        sys.exit(1)

    if not force:
        answer = input(f"Delete container '{name}'? This cannot be undone. [y/N] ")
        if answer.lower() not in ("y", "yes"):
            print("Aborted.")
            return

    print(f"Deleting container '{name}'...")
    _lxc("delete", cname, "--force")
    print(f"Container '{name}' deleted.")
