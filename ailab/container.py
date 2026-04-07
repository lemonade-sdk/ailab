"""LXD container management for ailab — via LXD REST API (pylxd)."""

import os
import pwd
import socket
import sys
import textwrap
import time
from pathlib import Path

import pylxd
import pylxd.exceptions

# ── Constants ─────────────────────────────────────────────────────────────────

AILAB_PROJECT = "ailab"
BASE_IMAGE_SERVER = "https://cloud-images.ubuntu.com/daily/"
BASE_IMAGE_ALIAS = "devel"

# Ports proxied INTO the container (container localhost → host service)
# Apps in the container connect to these as if they're local, but they reach the host.
INBOUND_PROXIES = [
    ("lemonade", 8000),   # lemonade-server
    ("ollama",   11434),  # ollama
]

# Ports proxied FROM the container to the host (host browser → container service).
# Kept empty — each installer adds only the ports its tool actually uses.
OUTBOUND_PROXIES: list = []



# ── API clients ───────────────────────────────────────────────────────────────

def _client() -> pylxd.Client:
    """Return a pylxd Client scoped to the ailab project."""
    return pylxd.Client(project=AILAB_PROJECT)


def _admin_client() -> pylxd.Client:
    """Return a pylxd Client for admin operations (project/profile management)."""
    return pylxd.Client()


# ── User helpers ──────────────────────────────────────────────────────────────

def _container_name(name: str) -> str:
    """Return the container name as-is; the LXD project provides isolation."""
    return name


def _current_user():
    uid = os.getuid()
    gid = os.getgid()
    pw = pwd.getpwuid(uid)
    return pw.pw_name, uid, gid, pw.pw_dir


def _user_info(username: str) -> tuple[str, int, int, str]:
    """Return (username, uid, gid, home) for the given username."""
    pw = pwd.getpwnam(username)
    return pw.pw_name, pw.pw_uid, pw.pw_gid, pw.pw_dir


def list_system_users() -> list[dict]:
    """Return all /etc/passwd users with UID >= 1000 (excludes nobody)."""
    users = []
    for pw in pwd.getpwall():
        if pw.pw_uid >= 1000 and pw.pw_uid < 65534:
            users.append({
                "username": pw.pw_name,
                "uid": pw.pw_uid,
                "home": pw.pw_dir,
            })
    return sorted(users, key=lambda u: u["uid"])


def get_container_user(cname: str) -> tuple[str, int, int, str]:
    """Return (username, uid, gid, home) for the user mapped into a container.

    Reads 'user.ailab-mapped-user' from the LXD instance config, which is
    stored at creation time.  Falls back to the current process user for
    backward compatibility with containers created before this feature.
    """
    try:
        instance = _client().instances.get(cname)
        mapped = instance.config.get("user.ailab-mapped-user")
        if mapped:
            return _user_info(mapped)
    except Exception:
        pass
    return _current_user()


# ── Instance helpers ──────────────────────────────────────────────────────────

def _get_instance(cname: str):
    """Return the named Instance, raising RuntimeError if not found."""
    try:
        return _client().instances.get(cname)
    except pylxd.exceptions.NotFound:
        raise RuntimeError(f"Container '{cname}' not found.")


def _container_status(cname: str) -> str:
    """Return container status string or 'missing'."""
    try:
        return _client().instances.get(cname).status.lower()
    except pylxd.exceptions.NotFound:
        return "missing"


def _wait_for_network(cname: str, timeout: int = 60):
    """Wait until the container has an IPv4 address."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            state = _get_instance(cname).state()
            for iface in (state.network or {}).values():
                for addr in iface.get("addresses", []):
                    if addr["family"] == "inet" and not addr["address"].startswith("127."):
                        return
        except (RuntimeError, pylxd.exceptions.LXDAPIException):
            pass
        time.sleep(2)
    raise TimeoutError(f"Container {cname} did not get a network address within {timeout}s")


def _wait_for_ready(cname: str, timeout: int = 30):
    """Wait until we can exec a command in the container."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = _get_instance(cname).execute(["true"])
            if result.exit_code == 0:
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"Container {cname} not ready after {timeout}s")


def _host_port_in_use(port: int) -> bool:
    """Return True if a TCP port is already bound on the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def _partition_conflicting_proxies(
    devices: dict,
) -> tuple[dict, dict]:
    """Split devices into (conflicting_outbound_proxies, rest).

    conflicting: outbound proxy devices whose host listen port is already in use.
    rest: all other devices (safe to apply before starting).
    """
    conflicting: dict = {}
    rest: dict = {}
    for name, cfg in devices.items():
        if (
            cfg.get("type") == "proxy"
            and cfg.get("bind", "host") == "host"
            and ":" in cfg.get("listen", "")
        ):
            try:
                port = int(cfg["listen"].rsplit(":", 1)[-1])
                if _host_port_in_use(port):
                    conflicting[name] = cfg
                    continue
            except ValueError:
                pass
        rest[name] = cfg
    return conflicting, rest


# ── Default profile devices ───────────────────────────────────────────────────

def _default_profile_devices() -> dict[str, dict[str, str]]:
    """Return root/nic devices from the host's default LXD profile."""
    fallback = {
        "eth0": {"name": "eth0", "network": "lxdbr0", "type": "nic"},
        "root": {"path": "/", "pool": "default", "type": "disk"},
    }
    try:
        devices = _admin_client().profiles.get("default").devices
        selected = {}
        if "eth0" in devices:
            selected["eth0"] = {str(k): str(v) for k, v in devices["eth0"].items()}
        if "root" in devices:
            selected["root"] = {str(k): str(v) for k, v in devices["root"].items()}
        selected.setdefault("eth0", fallback["eth0"])
        selected.setdefault("root", fallback["root"])
        return selected
    except Exception:
        return fallback


# ── Config dir ────────────────────────────────────────────────────────────────

def _ailab_data_root() -> Path:
    """Base directory for ailab's persistent data.

    When running as a snap, use SNAP_COMMON (/var/snap/ailab/common) which is
    always accessible to the snap daemon regardless of which user it runs as.
    Falls back to the standard XDG location for non-snap installs.
    """
    snap_common = os.environ.get("SNAP_COMMON")
    if snap_common:
        return Path(snap_common)
    if xdg := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg) / "ailab"
    return Path.home() / ".local" / "share" / "ailab"


def container_config_dir(name: str, home: str) -> Path:
    """Per-container config directory on the host.

    Non-snap: inside the home bind-mount at home/.local/share/ailab/containers/{name}
    Snap: under SNAP_COMMON/containers/{username}/{name}.  The directory is
    chowned to the mapped user so the in-container user can write to it, and
    a separate LXD disk device mounts it at the same path inside the container.
    """
    if os.environ.get("SNAP_COMMON"):
        username = Path(home).name
        return _ailab_data_root() / "containers" / username / name
    return Path(home) / ".local" / "share" / "ailab" / "containers" / name


def build_shell_welcome(container_name: str) -> str:
    """Build a contextual SHELL_WELCOME message based on installed tools."""
    import json as _json
    cname = _container_name(container_name)
    _, _, _, home = get_container_user(cname)
    cfg_root = container_config_dir(container_name, home)
    openclaw_json = cfg_root / "openclaw" / "openclaw.json"

    lines = ["Welcome to your AI Lab container!\n"]

    if openclaw_json.exists():
        # Read gateway shared token from config — used in the dashboard URL
        gateway_token = None
        try:
            data = _json.loads(openclaw_json.read_text())
            gateway_token = data.get("gateway", {}).get("auth", {}).get("token")
        except Exception:
            pass

        if gateway_token:
            lines += [
                "openclaw is ready — launch the AI assistant:",
                "  openclaw",
                "",
                "  Opens the TUI to chat with your local LLM.",
                f"  The gateway web UI is available at http://localhost:18789/#token={gateway_token}",
            ]
        else:
            lines += [
                "openclaw is installed but needs to be set up.",
                "Run the setup wizard:",
                "  openclaw onboard",
                "",
                "  This connects openclaw to your local LLM (lemonade/ollama).",
                "  After onboarding, launch the TUI with:  openclaw",
            ]
    else:
        lines += [
            "No AI tools are installed yet.",
            "From the host, install a tool into this container:",
            "  ailab install openclaw " + container_name,
        ]

    return "\n".join(lines)


# ── File push ─────────────────────────────────────────────────────────────────

def push_file(cname: str, remote_path: str, content: bytes | str):
    """Write content to a file inside the container via the LXD files API."""
    if isinstance(content, str):
        content = content.encode()
    _get_instance(cname).files.put(remote_path, content)


# ── Environment variables ─────────────────────────────────────────────────────

def set_container_env(cname: str, env: dict[str, str], profile_name: str | None = None):
    """Persist environment variables in the container.

    Sets them via both LXD config (available to exec calls) and a
    /etc/profile.d/ script (survives PAM re-initialization in login shells).
    """
    instance = _get_instance(cname)
    for key, value in env.items():
        instance.config[f"environment.{key}"] = value
    instance.save(wait=True)

    tag = profile_name or "container"
    lines = [f"# ailab: {tag} environment (auto-generated)"]
    for key, value in env.items():
        lines.append(f'export {key}="{value}"')
    script = "\n".join(lines) + "\n"
    instance.files.put(f"/etc/profile.d/ailab-{tag}.sh", script.encode())


# ── Public exec API (used by installers) ─────────────────────────────────────

def container_exec(
    cname: str,
    cmd: list[str],
    *,
    uid: int | None = None,
    gid: int | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdin: bytes | str | None = None,
    check: bool = True,
    stream: bool = False,
) -> tuple[int, str, str]:
    """Execute a command in a container. Returns (exit_code, stdout, stderr).

    stream: if True, print stdout/stderr to the terminal in real-time.
    check:  if True, raise RuntimeError on non-zero exit code.
    """
    instance = _get_instance(cname)

    kwargs: dict = {}
    if uid is not None:
        kwargs["user"] = uid
    if gid is not None:
        kwargs["group"] = gid
    if cwd is not None:
        kwargs["cwd"] = cwd
    if env:
        kwargs["environment"] = env
    if stdin is not None:
        kwargs["stdin_payload"] = stdin.encode() if isinstance(stdin, str) else stdin
    if stream:
        kwargs["stdout_handler"] = lambda s: print(s, end="", flush=True)
        kwargs["stderr_handler"] = lambda s: print(s, end="", file=sys.stderr, flush=True)

    result = instance.execute(cmd, **kwargs)

    if check and result.exit_code != 0:
        raise RuntimeError(
            f"Command {cmd!r} in '{cname}' failed (exit {result.exit_code}):\n"
            f"{result.stderr or ''}"
        )
    return result.exit_code, result.stdout or "", result.stderr or ""


# ── Public device API (used by installers) ───────────────────────────────────

def has_device(cname: str, device_name: str) -> bool:
    """Return True if the container has a device with the given name."""
    try:
        return device_name in _get_instance(cname).expanded_devices
    except RuntimeError:
        return False


def add_proxy_device(
    cname: str,
    device_name: str,
    listen: str,
    connect: str,
    bind: str = "host",
) -> bool:
    """Add a proxy device to the container. Returns False if port already in use."""
    instance = _get_instance(cname)
    if device_name in instance.expanded_devices:
        return True
    instance.devices[device_name] = {
        "type": "proxy",
        "listen": listen,
        "connect": connect,
        "bind": bind,
    }
    try:
        instance.save(wait=True)
        return True
    except pylxd.exceptions.LXDAPIException as e:
        msg = str(e).lower()
        if "already in use" in msg or "address already" in msg:
            return False
        raise


def remove_proxy_device(cname: str, device_name: str):
    """Remove a proxy device from the container."""
    instance = _get_instance(cname)
    if device_name in instance.devices:
        del instance.devices[device_name]
        instance.save(wait=True)


# ── Start container (used by installers) ─────────────────────────────────────

def start_container(cname: str):
    """Start a stopped container and wait until it is ready.

    Proxy devices whose host port is already bound by another process are
    temporarily removed before starting and restored afterwards so that the
    container can still start even when another container holds a shared port.
    """
    instance = _get_instance(cname)
    conflicting, safe_devices = _partition_conflicting_proxies(instance.devices or {})

    if conflicting:
        names = ", ".join(sorted(conflicting))
        print(f"Warning: host ports already in use — skipping proxy device(s): {names}")
        instance.devices = safe_devices
        instance.save(wait=True)

    try:
        instance.start(wait=True)
    except pylxd.exceptions.LXDAPIException:
        if conflicting:
            # Restore removed devices even on failure
            instance = _get_instance(cname)
            instance.devices = {**instance.devices, **conflicting}
            instance.save(wait=True)
        raise

    _wait_for_ready(cname)

    if conflicting:
        # Restore the proxy devices so they work when the port is freed later
        instance = _get_instance(cname)
        instance.devices = {**instance.devices, **conflicting}
        instance.save(wait=True)


# ── Cloud-init user-data ──────────────────────────────────────────────────────

def _cloud_init_userdata(username: str, uid: int, gid: int, home: str) -> str:
    """Generate cloud-init user-data YAML for container provisioning.

    Replaces container_init.sh: installs base packages, Node.js, sets up
    the user account, and writes /etc/profile.d/ailab.sh.
    """
    # Interpolated via .replace() to avoid f-string collisions with shell ${...}
    user_setup = textwrap.dedent("""\
        #!/bin/bash
        set -euo pipefail
        USERNAME="__USERNAME__"
        USER_UID=__UID__
        USER_GID=__GID__
        USER_HOME="__HOME__"

        log() { echo "[ailab] $*"; }

        log "Setting up user $USERNAME (uid=$USER_UID, gid=$USER_GID)"

        EXISTING_GROUP=$(getent group "$USER_GID" | cut -d: -f1 || true)
        if [ -n "${EXISTING_GROUP:-}" ] && [ "$EXISTING_GROUP" != "$USERNAME" ]; then
            log "Renaming group '$EXISTING_GROUP' -> '$USERNAME'"
            groupmod -n "$USERNAME" "$EXISTING_GROUP"
        elif [ -z "${EXISTING_GROUP:-}" ]; then
            groupadd -g "$USER_GID" "$USERNAME"
        fi

        EXISTING_USER=$(getent passwd "$USER_UID" | cut -d: -f1 || true)
        if [ -n "${EXISTING_USER:-}" ] && [ "$EXISTING_USER" != "$USERNAME" ]; then
            log "Renaming user '$EXISTING_USER' -> '$USERNAME'"
            usermod -l "$USERNAME" -d "$USER_HOME" -s /bin/bash "$EXISTING_USER"
        elif [ -z "${EXISTING_USER:-}" ]; then
            useradd --uid "$USER_UID" --gid "$USER_GID" --shell /bin/bash \
                    --no-create-home --home-dir "$USER_HOME" "$USERNAME"
        fi

        echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/$USERNAME"
        chmod 0440 "/etc/sudoers.d/$USERNAME"

        loginctl enable-linger "$USERNAME" \
            || log "Warning: loginctl enable-linger failed (non-fatal)"
        systemctl start "user@${USER_UID}.service" \
            || log "Warning: could not start user session (non-fatal)"

        sudo -u "$USERNAME" bash -c 'curl -fsSL https://bun.sh/install | bash' \
            || log "Warning: Bun install failed (non-fatal)"

        sudo -u "$USERNAME" bash -c \
            'NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' \
            || log "Warning: Homebrew install failed (non-fatal)"

        log "User setup complete."
        """).replace("__USERNAME__", username) \
            .replace("__UID__", str(uid)) \
            .replace("__GID__", str(gid)) \
            .replace("__HOME__", home)

    profile_sh = textwrap.dedent("""\
        # ailab environment
        export LANG=en_US.UTF-8
        export LC_ALL=en_US.UTF-8

        # Homebrew
        if [ -d "/home/linuxbrew/.linuxbrew" ]; then
            eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
        fi

        # Bun
        if [ -d "$HOME/.bun" ]; then
            export BUN_INSTALL="$HOME/.bun"
            export PATH="$BUN_INSTALL/bin:$PATH"
        fi

        # pipx
        export PATH="$PATH:$HOME/.local/bin"

        # bash completion
        if [ -n "${BASH_VERSION:-}" ] && [ -r /usr/share/bash-completion/bash_completion ]; then
            . /usr/share/bash-completion/bash_completion
        fi
        """)

    def _indent(text: str, spaces: int = 6) -> str:
        return textwrap.indent(text, " " * spaces)

    return (
        "#cloud-config\n"
        "\n"
        "locale: en_US.UTF-8\n"
        "\n"
        # Disable ssh_authkey_fingerprints: it fails in LXD containers because
        # SSH host keys aren't generated yet when the module runs.
        "no_ssh_fingerprints: true\n"
        "\n"
        "package_update: true\n"
        "package_upgrade: false\n"
        "\n"
        "packages:\n"
        "  - python3\n"
        "  - python3-venv\n"
        "  - python3-pip\n"
        "  - python3-dev\n"
        "  - pipx\n"
        "  - git\n"
        "  - curl\n"
        "  - wget\n"
        "  - build-essential\n"
        "  - ca-certificates\n"
        "  - gnupg\n"
        "  - sudo\n"
        "  - bash-completion\n"
        "  - locales\n"
        "  - unzip\n"
        "  - zip\n"
        "  - jq\n"
        "  - htop\n"
        "  - vim\n"
        "  - nano\n"
        "  - file\n"
        "  - lsb-release\n"
        "  - xdg-utils\n"
        "  - socat\n"
        "  - netcat-openbsd\n"
        "  - dbus-user-session\n"
        "  - systemd-container\n"
        "\n"
        "write_files:\n"
        "  - path: /tmp/ailab-setup-user.sh\n"
        "    permissions: '0755'\n"
        "    content: |\n"
        f"{_indent(user_setup)}"
        "  - path: /etc/profile.d/ailab.sh\n"
        "    permissions: '0644'\n"
        "    content: |\n"
        f"{_indent(profile_sh)}"
        "\n"
        "runcmd:\n"
        "  - [bash, -c, 'curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -']\n"
        "  - [apt-get, install, -y, -q, nodejs]\n"
        "  - [npm, install, -g, npm@latest]\n"
        "  - [bash, /tmp/ailab-setup-user.sh]\n"
    )


# ── Project and profile setup ─────────────────────────────────────────────────

def ensure_ailab_project():
    """Create the ailab LXD project and profile if they don't exist."""
    admin = _admin_client()
    client = _client()

    try:
        admin.projects.get(AILAB_PROJECT)
    except pylxd.exceptions.NotFound:
        print(f"Creating LXD project '{AILAB_PROJECT}'...")
        admin.projects.create({
            "name": AILAB_PROJECT,
            "config": {"features.images": "false"},
        })

    profile_config = {"security.nesting": "true"}
    devices = _default_profile_devices()

    try:
        profile = client.profiles.get(AILAB_PROJECT)
        profile.config = profile_config
        profile.devices = devices
        profile.save()
    except pylxd.exceptions.NotFound:
        print(f"Creating LXD profile '{AILAB_PROJECT}'...")
        client.profiles.create({
            "name": AILAB_PROJECT,
            "config": profile_config,
            "devices": devices,
        })


# ── Container creation ────────────────────────────────────────────────────────

def create_container(
    name: str,
    extra_outbound_ports: list[tuple[int, int]] | None = None,
    username: str | None = None,
):
    """Create and fully configure a new ailab container.

    extra_outbound_ports: list of (host_port, container_port) tuples to add
                          in addition to the defaults.
    username: the host user to map into the container; defaults to the
              current user.  Useful when the server runs as root (e.g. snap).
    """
    cname = _container_name(name)
    if username:
        username, uid, gid, home = _user_info(username)
    else:
        username, uid, gid, home = _current_user()

    if _container_status(cname) != "missing":
        status = _container_status(cname)
        print(f"Container '{name}' already exists (status: {status}).")
        sys.exit(1)

    ensure_ailab_project()

    # Pre-create config dir on host (accessible in container via bind mount)
    cfg_dir = container_config_dir(name, home)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    # Ensure the mapped user can write into the directory.  Prefer chown, but
    # fall back to chmod 0o777 when running under snap (seccomp blocks chown).
    try:
        os.chown(cfg_dir, uid, gid)
    except OSError:
        cfg_dir.chmod(0o777)

    # ── Build devices dict ────────────────────────────────────────────────────
    devices: dict[str, dict] = {}

    # Home directory bind-mount
    devices["homedir"] = {"type": "disk", "source": home, "path": home}

    # When running as snap, cfg_dir lives under SNAP_COMMON (outside home),
    # so it needs its own bind-mount to be accessible inside the container.
    if not str(cfg_dir).startswith(home):
        devices["ailab-config"] = {
            "type": "disk",
            "source": str(cfg_dir),
            "path": str(cfg_dir),
        }

    # Inbound proxies: container localhost → host service
    for dev_name, port in INBOUND_PROXIES:
        devices[f"proxy-in-{dev_name}"] = {
            "type": "proxy",
            "listen": f"tcp:127.0.0.1:{port}",
            "connect": f"tcp:127.0.0.1:{port}",
            "bind": "container",
        }

    # Outbound proxies: host → container web UIs
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
        devices[f"proxy-out-{dev_name}"] = {
            "type": "proxy",
            "listen": f"tcp:127.0.0.1:{host_port}",
            "connect": f"tcp:127.0.0.1:{container_port}",
            "bind": "host",
        }

    # ── Build instance config ─────────────────────────────────────────────────
    idmap = f"uid {uid} {uid}\ngid {gid} {gid}"
    config = {
        "name": cname,
        "source": {
            "type": "image",
            "protocol": "simplestreams",
            "server": BASE_IMAGE_SERVER,
            "alias": BASE_IMAGE_ALIAS,
        },
        "profiles": [AILAB_PROJECT],
        "config": {
            "raw.idmap": idmap,
            "security.nesting": "true",
            "user.user-data": _cloud_init_userdata(username, uid, gid, home),
            f"environment.AILAB_CONFIG_DIR": str(cfg_dir),
            "user.ailab-mapped-user": username,
        },
        "devices": devices,
    }

    # ── Create and start ──────────────────────────────────────────────────────
    print(f"Creating container '{cname}' from {BASE_IMAGE_ALIAS} ({BASE_IMAGE_SERVER})...")
    client = _client()

    # Remove any proxy devices that conflict with in-use ports (best-effort)
    safe_devices = {}
    for dev_name, dev_cfg in devices.items():
        if dev_cfg.get("type") == "proxy" and dev_cfg.get("bind") == "host":
            safe_devices[dev_name] = dev_cfg
        else:
            safe_devices[dev_name] = dev_cfg
    config["devices"] = safe_devices

    instance = client.instances.create(config, wait=True)
    print(f"Starting container '{cname}'...")
    instance.start(wait=True)

    print("Waiting for network...")
    _wait_for_network(cname)

    # ── Wait for cloud-init to complete ───────────────────────────────────────
    print("Running container initialization via cloud-init (this may take a few minutes)...")
    instance = _get_instance(cname)
    instance.execute(
        ["cloud-init", "status", "--wait"],
        stdout_handler=lambda s: print(s, end="", flush=True),
        stderr_handler=lambda s: print(s, end="", file=sys.stderr, flush=True),
    )
    # Verify cloud-init did not error
    rc, out, _ = container_exec(cname, ["cloud-init", "status"], check=False)
    if rc != 0 or "error" in out.lower():
        print(f"Warning: cloud-init may have encountered errors: {out.strip()}")
        # Dump the last 60 lines of the output log for diagnosis
        _, log_out, _ = container_exec(
            cname,
            ["tail", "-n", "60", "/var/log/cloud-init-output.log"],
            check=False,
        )
        if log_out.strip():
            print("--- cloud-init-output.log (last 60 lines) ---")
            print(log_out)
            print("---")

    # Write the AILAB_CONFIG_DIR profile.d snippet (config env is already set above)
    _get_instance(cname).files.put(
        "/etc/profile.d/ailab-base.sh",
        f'# ailab: base environment (auto-generated)\nexport AILAB_CONFIG_DIR="{cfg_dir}"\n'.encode(),
    )

    print(f"\nContainer '{name}' is ready!")
    print(f"  Run:   ailab run {name}")
    print(f"  Shell: lxc --project {AILAB_PROJECT} exec {cname} --user {uid} -- /bin/bash -l")


# ── Port management ───────────────────────────────────────────────────────────

def add_port(name: str, host_port: int, container_port: int, direction: str = "outbound"):
    """Add a port proxy to a container.

    direction: 'outbound' (host → container, for web UIs)
               'inbound'  (container → host, for host services)
    """
    cname = _container_name(name)
    if _container_status(cname) == "missing":
        print(f"Container '{name}' not found.")
        sys.exit(1)

    if direction == "outbound":
        dev_name = f"proxy-out-custom-{host_port}"
        ok = add_proxy_device(cname, dev_name,
                               f"tcp:127.0.0.1:{host_port}",
                               f"tcp:127.0.0.1:{container_port}",
                               bind="host")
        if not ok:
            print(f"Error: port {host_port} is already in use on the host.")
            sys.exit(1)
        print(f"Added outbound proxy: host:{host_port} → container:{container_port}")
    else:
        dev_name = f"proxy-in-custom-{container_port}"
        add_proxy_device(cname, dev_name,
                          f"tcp:127.0.0.1:{container_port}",
                          f"tcp:127.0.0.1:{host_port}",
                          bind="container")
        print(f"Added inbound proxy: container:{container_port} → host:{host_port}")


def remove_port(name: str, host_port: int, direction: str = "outbound"):
    """Remove a custom port proxy from a container."""
    cname = _container_name(name)
    if _container_status(cname) == "missing":
        print(f"Container '{name}' not found.")
        sys.exit(1)

    dev_name = (f"proxy-out-custom-{host_port}" if direction == "outbound"
                else f"proxy-in-custom-{host_port}")
    remove_proxy_device(cname, dev_name)
    print(f"Removed proxy device '{dev_name}'")


def list_ports(name: str):
    """List all proxy devices on a container."""
    cname = _container_name(name)
    try:
        instance = _get_instance(cname)
    except RuntimeError:
        print(f"Container '{name}' not found.")
        sys.exit(1)

    proxies = {k: v for k, v in instance.expanded_devices.items()
               if v.get("type") == "proxy"}
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

def run_container(name: str, post_cmds: list[str] | None = None):
    """Start the container (if needed) and open a user shell.

    post_cmds: optional shell commands to run before the interactive shell,
               e.g. ["openclaw onboard"].  Each command runs in sequence; if
               one exits non-zero the shell still opens.  The final shell is
               a login shell so profile.d wrappers are active.
    """
    cname = _container_name(name)
    username, uid, gid, home = _current_user()

    status = _container_status(cname)
    if status == "missing":
        print(f"Container '{name}' not found. Create it with: ailab new {name}")
        sys.exit(1)

    if status != "running":
        print(f"Starting container '{name}'...")
        _get_instance(cname).start(wait=True)
        _wait_for_ready(cname)

    print(f"Opening shell in '{name}' as {username}...")

    if post_cmds:
        chain = "; ".join(post_cmds)
        exec_argv = ["/bin/bash", "--login", "-c", f"{chain}; exec bash --login"]
    else:
        exec_argv = ["/bin/bash", "--login"]

    # Use lxc exec for the interactive shell — it's the only operation that
    # needs a real PTY, which the REST API exec doesn't provide cleanly.
    exec_args = [
        "lxc", "--project", AILAB_PROJECT,
        "exec", cname,
        f"--user={uid}",
        f"--group={gid}",
        f"--env=HOME={home}",
        f"--env=USER={username}",
        f"--env=LOGNAME={username}",
        f"--env=XDG_RUNTIME_DIR=/run/user/{uid}",
        f"--env=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
        "--env=TERM=xterm-256color",
        f"--env=SHELL_WELCOME={build_shell_welcome(name)}",
        f"--cwd={home}",
        "--",
        *exec_argv,
    ]
    os.execvp(exec_args[0], exec_args)


def stop_container(name: str):
    """Stop a running container."""
    cname = _container_name(name)
    status = _container_status(cname)

    if status == "missing":
        print(f"Container '{name}' not found.")
        sys.exit(1)

    if status != "running":
        print(f"Container '{name}' is not running (status: {status}).")
        return

    print(f"Stopping container '{name}'...")
    _get_instance(cname).stop(wait=True)
    print(f"Container '{name}' stopped.")


# ── List ──────────────────────────────────────────────────────────────────────

def list_containers():
    """List all ailab containers."""
    client = _client()
    # instances.all() has a project-scoping bug in pylxd 2.4.x that appends
    # '?project=...' to instance names; use the raw API instead.
    resp = client.api.instances.get(params={"recursion": "1"})
    containers = resp.json().get("metadata", [])

    if not containers:
        print("No ailab containers found.")
        print("Create one with: ailab new <name>")
        return

    print(f"{'NAME':<25} {'STATUS':<12} {'IPv4':<18} {'OUTBOUND PORTS'}")
    print("-" * 80)
    for c in containers:
        cname = c["name"]
        status = c.get("status", "unknown")
        ipv4 = ""

        # Fetch live state for IP address
        try:
            state = client.instances.get(cname).state()
            for iface in (state.network or {}).values():
                for addr in iface.get("addresses", []):
                    if addr["family"] == "inet" and not addr["address"].startswith("127."):
                        ipv4 = addr["address"]
                        break
        except Exception:
            pass

        devices = c.get("expanded_devices", {})
        ports = [
            cfg.get("listen", "").rsplit(":", 1)[-1]
            for cfg in devices.values()
            if cfg.get("type") == "proxy" and cfg.get("bind", "host") == "host"
            and ":" in cfg.get("listen", "")
        ]
        ports_str = ",".join(sorted(ports, key=int)) if ports else "-"
        print(f"{cname:<25} {status:<12} {ipv4:<18} {ports_str}")


def completion_container_names() -> list[str]:
    """Return container names for shell completion."""
    try:
        client = _client()
        resp = client.api.instances.get(params={"recursion": "1"})
        return sorted(c["name"] for c in resp.json().get("metadata", []) if c.get("name"))
    except Exception:
        return []


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_container(name: str, force: bool = False):
    """Stop and delete a container and its host-side data directory."""
    import shutil
    cname = _container_name(name)
    if _container_status(cname) == "missing":
        print(f"Container '{name}' not found.")
        sys.exit(1)

    if not force:
        answer = input(f"Delete container '{name}'? This cannot be undone. [y/N] ")
        if answer.lower() not in ("y", "yes"):
            print("Aborted.")
            return

    # Read the mapped user before deletion so we know where data lives.
    _, _, _, home = get_container_user(cname)
    data_dir = container_config_dir(name, home)

    print(f"Deleting container '{name}'...")
    instance = _get_instance(cname)
    if instance.status == "Running":
        instance.stop(force=True, wait=True)
    instance.delete(wait=True)

    try:
        if data_dir.exists():
            print(f"Removing container data directory: {data_dir}")
            shutil.rmtree(data_dir, ignore_errors=True)
    except OSError:
        pass  # Path inaccessible (e.g. snap confinement on old-style hidden dir)

    print(f"Container '{name}' deleted.")

