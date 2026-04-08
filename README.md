# AI Lab

Run AI tools safely on Ubuntu — no technical experience required.

AI Lab creates lightweight [LXD](https://ubuntu.com/lxd) containers that are
pre-wired to use AI services running on your host's lemonade-server.
Each container shares your home directory, so your files are always accessible,
while keeping installed software isolated from the rest of your system.

## Features

- **Safe by default** — AI tools run in isolated containers, not on your host system
- **Your files, always accessible** — home directory is shared into every container
- **Local AI, zero config** — lemonade-server and ollama are automatically available
  inside containers on `localhost`, proxied from the host
- **One command, fully configured** — `ailab new mybox --install openclaw` creates
  a container, installs the tool, runs onboarding, and drops you into a shell
- **Web UIs in your browser** — common ports are forwarded so you can open web
  interfaces at `http://localhost:PORT` from your host browser
- **Organised in one place** — all ailab containers live in an LXD project named
  `ailab`, keeping them separate from any other LXD containers you have
- **Web management interface** — `ailab web` starts a browser-based UI for
  creating and managing containers with a built-in terminal and live logs

## Requirements

- Ubuntu 22.04 or later (Ubuntu 24.04 / 26.04 recommended)
- [LXD](https://ubuntu.com/lxd) installed and initialised (`lxd init`)
- Python 3.11 or later

## Installation

### Add your user to the `lxd` group

All installation methods require your user to be in the `lxd` group so
the `ailab` CLI can talk to LXD without `sudo`:

```bash
sudo usermod -aG lxd $USER
newgrp lxd   # apply without logging out, or log out and back in
```

### Snap (recommended)

```bash
sudo snap install lxd
sudo lxd init --auto
sudo snap install ailab
sudo snap connect ailab:lxd lxd:lxd
```

The web management interface runs as a daemon automatically after install.
Configure the host and port with snap settings:

```bash
snap set ailab web.host=127.0.0.1   # default: 127.0.0.1
snap set ailab web.port=11500        # default: 11500
```

Then open `http://127.0.0.1:11500` in your browser.

### From the PPA

```bash
sudo add-apt-repository ppa:ken-vandine/ailab
sudo apt install ailab
```

### From source

Install LXD:
```bash
sudo snap install lxd
sudo lxd init --auto
```

```bash
git clone https://github.com/kenvandine/ailab
cd ailab
./install.sh
```

The installer uses `pipx` if available (recommended), otherwise falls back to
a local virtual environment with a wrapper script in `~/.local/bin`.

After installation, ensure `~/.local/bin` is on your `PATH`:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## Quick Start

```bash
# Create a sandbox with openclaw installed — runs onboarding then drops to a shell
ailab new mybox --install openclaw
```

Or step by step:

```bash
ailab new mybox               # create sandbox
ailab install mybox openclaw  # install and configure openclaw
ailab run mybox               # open a shell
```

## Commands

### `ailab new <name>`

Create a new sandbox container. This:
- Launches an Ubuntu daily container in the `ailab` LXD project
- Mounts your home directory at the same path inside the container
- Sets up proxy devices so `localhost:8000` / `localhost:13305` (lemonade)
  and `localhost:11434` (ollama) inside the container reach the corresponding
  services on your host
- Forwards common web UI ports to your host browser
- Pre-installs: python3, pip, nodejs, npm, bun, homebrew

```bash
ailab new mybox

# Install a package immediately after creation (onboards and drops to shell)
ailab new mybox --install openclaw

# With extra port forwarding
ailab new mybox --port 5000:5000 --install openclaw
```

### `ailab run <name>`

Start the container (if stopped) and open an interactive shell.

```bash
ailab run mybox
```

### `ailab stop <name>`

Stop a running container.

```bash
ailab stop mybox
```

### `ailab list`

List all ailab containers with their status and forwarded ports.

```bash
ailab list
ailab ls      # alias
```

### `ailab delete <name>`

Stop and permanently delete a container.

```bash
ailab delete mybox
ailab delete mybox --force   # skip confirmation
```

### `ailab install <name> <package>`

Install a pre-configured AI tool into a container. Tools are configured
with opinionated local-AI defaults and cloud providers disabled.

```bash
ailab install mybox openclaw
ailab install mybox nullclaw
ailab install mybox picoclaw
```

### `ailab packages`

List all available installable packages.

```bash
ailab packages
ailab pkgs    # alias
```

### `ailab web`

Start the web management interface. Opens a browser-based dashboard for
creating, starting, stopping, and deleting containers. Includes:

- Container cards with status, IP address, and port chips
- Create containers with package selection and live progress stream
- Install packages with a live progress log
- Interactive in-browser terminal (full PTY, powered by xterm.js)
- Live container log tail (`journalctl -f`)
- Port proxy management (add/remove proxy devices)

```bash
ailab web                    # binds to 127.0.0.1:11500
ailab web --host 0.0.0.0    # expose on the local network
ailab web --port 9000        # use a different port
ailab web --reload           # auto-reload on code changes (development)
```

Then open `http://127.0.0.1:11500` in your browser.

### `ailab port`

Manage port proxies on a container.

```bash
# Expose port 9000 in the container on port 9000 of your host
ailab port add mybox 9000

# Expose a different host port than container port
ailab port add mybox 9001 9000

# Add an inbound proxy (container → host service)
ailab port add mybox 5001 --inbound

# List all port proxies
ailab port list mybox

# Remove a proxy
ailab port remove mybox 9000
```

## Installable Packages

| Package | Status | Description |
|---------|--------|-------------|
| `openclaw` | Supported | AI coding agent with local-first LLM support. Web UI at `http://127.0.0.1:18789`. |
| `nullclaw` | Experimental (CLI only) | Lightweight static-binary AI agent gateway (Zig-built). Web UI at `http://127.0.0.1:3000`. |
| `picoclaw` | Experimental (CLI only) | Ultra-lightweight Go-based AI agent gateway (30+ providers). Web UI at `http://127.0.0.1:18800`. |

All packages use lemonade-server as the primary provider via its
OpenAI-compatible API, with cloud providers disabled. lemonade-server is
auto-detected on `localhost:13305` (>= 10.1) or `localhost:8000` (< 10.1).
`nullclaw` and `picoclaw` also configure ollama on `localhost:11434` as a
secondary provider.

## How It Works

```
Your Host
├── lemonade-server :13305 (>= 10.1) or :8000 (< 10.1)
├── ollama          :11434
└── ailab container (LXD)
    ├── localhost:13305  →  host:13305  (lemonade >= 10.1, inbound proxy)
    ├── localhost:8000   →  host:8000   (lemonade < 10.1,  inbound proxy)
    ├── localhost:11434  →  host:11434  (ollama, inbound proxy)
    ├── host:7860        →  container:7860   (gradio)
    ├── host:8888        →  container:8888   (jupyter)
    ├── host:8501        →  container:8501   (streamlit)
    └── host:9090        →  container:9090
```

Tool-specific ports (e.g. nullclaw :3000, openclaw :18789) are added when
the package is installed, not at container creation time.

**LXD REST API**: All container operations use the LXD REST API via `pylxd`,
not the `lxc` CLI. Container setup runs via cloud-init at creation time,
so no restart is needed and configuration is applied atomically.

**LXD project**: All containers are created inside the `ailab` LXD project,
keeping them separate from any other LXD containers on your system. You can
see them with `lxc --project ailab list`.

**Home directory**: Your host home directory is bind-mounted into the container
at the same path using `raw.idmap` for correct UID/GID passthrough. Files you
create inside the container appear on your host and vice versa.

**Per-container config**: Each container has an isolated home directory, so
tool configs (e.g. `~/.openclaw/openclaw.json`) are automatically per-container.
You can have two containers running the same tool with different configurations.

**Security nesting**: Containers are created with `security.nesting=true`,
which enables docker, fuse, and other tools that need kernel features inside
the container.

## Default Outbound Ports

These ports are forwarded from every new container to your host by default:

| Port | Common Use |
|------|-----------|
| 7860 | Gradio |
| 8888 | Jupyter |
| 8501 | Streamlit |
| 9090 | Prometheus, general |

Additional ports are forwarded when specific packages are installed:
- nullclaw: 3000
- openclaw: 18789
- picoclaw: 18800

When multiple containers are running, ailab automatically skips proxy devices
whose host port is already bound, so containers can start without conflicts.
Conflicting proxies are restored to the config so they activate once the port
is freed.

## Tips

**Web interface**: `ailab web` serves a React dashboard at
`http://127.0.0.1:11500`. The frontend communicates with a FastAPI backend
over REST, SSE (for live creation/install progress), and WebSockets
(interactive terminal and log tail).

**Multiple sandboxes**: Create separate containers for different projects:
```bash
ailab new coding --install openclaw
ailab new experiments --install openclaw
```

**Persistence**: Containers persist between reboots. LXD starts them
automatically. `ailab run` starts a stopped container before opening a shell.

**Reinstalling a package**: Just re-run `ailab install`. Config directories
are separate, so reinstalling updates the binary and rewrites config.

**LXD console**: You can also access containers directly:
```bash
lxc --project ailab list
lxc --project ailab exec mybox -- bash
```

## License

Copyright (C) 2026 Ken VanDine and contributors

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

See [LICENSE](LICENSE) for the full license text.
