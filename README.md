# AI Lab

Run AI tools safely on Ubuntu — no technical experience required.

AI Lab creates lightweight [LXD](https://ubuntu.com/lxd) containers that are
pre-wired to use AI services running on your host's lemonade-server.
Each container gets its own isolated home directory (visible on the host under
`~/ailab/<name>`), keeping both the software an agent installs and the files it
touches separate from the rest of your system.

## Features

- **Safe by default** — AI tools run in isolated containers, not on your host system
- **Isolated workspaces** — each container gets its own home directory,
  accessible from the host at `~/ailab/<name>`; your real home is not exposed
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

## Installation

### Snap (recommended)

```bash
sudo snap install lxd
sudo lxd init --auto
sudo snap install ailab
sudo snap connect ailab:lxd lxd:lxd
```

Confirm everything is wired up correctly:

```bash
ailab doctor
```

It checks that LXD is installed, initialised, and reachable, and reports
whether lemonade-server and ollama are available — with a remedy for anything
that's missing.

The web management interface runs as a daemon automatically after install.
Configure the host and port with snap settings:

```bash
snap set ailab web.host=127.0.0.1   # default: 127.0.0.1
snap set ailab web.port=11500        # default: 11500
```

The dashboard requires an access token (it controls containers and provides
interactive shells, so it is not left open to any local page or process).
Get a ready-to-open URL with:

```bash
sudo ailab dashboard
```

and open the printed `http://127.0.0.1:11500/#token=…` link in your browser.
The browser remembers the token, so this is only needed once per machine.

### From the PPA

```bash
sudo add-apt-repository ppa:ken-vandine/ailab
sudo apt install ailab
```

Both PPA and source installs require your user to be in the `lxd` group:

```bash
sudo usermod -aG lxd $USER
newgrp lxd   # apply without logging out, or log out and back in
```

### From source

Requires Python 3.11 or later. Install LXD:
```bash
sudo snap install lxd
sudo lxd init --auto
```

```bash
git clone https://github.com/lemonade-sdk/ailab
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
ailab shell mybox  # alias
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
ailab rm mybox        # alias
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
ailab web --host 0.0.0.0    # expose on the local network (trusted networks only)
ailab web --port 9000        # use a different port
ailab web --reload           # auto-reload on code changes (development)
```

Every `/api` route — including the shell and log WebSockets — requires a
bearer token, generated on first start and stored under the snap's data
directory (or `~/.local/share/ailab/web-token` for non-snap installs).
`ailab web` prints the tokenized dashboard URL at startup, and you can
retrieve it any time with:

```bash
ailab dashboard          # sudo ailab dashboard under the snap
```

Open the printed `http://127.0.0.1:11500/#token=…` URL; the frontend stores
the token in the browser and strips it from the address bar. Cloud-tunnel
access is unaffected: the hub authenticates you with GitHub OAuth and the
tunnel client presents the local token on your behalf.

Bound to `0.0.0.0` (or any wildcard address), both `ailab web` and
`ailab dashboard` print one tokenized link per address the dashboard is
actually reachable on — `localhost` plus every LAN/public IP ailab could
discover on the host — instead of just `localhost`, which wouldn't work from
another machine:

```
$ sudo ailab dashboard
http://localhost:11500/#token=…
http://192.168.1.50:11500/#token=…
```

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

By default, outbound proxies (host → container, the kind used for web UIs)
listen on `127.0.0.1` only — including the ones `ailab install` sets up
automatically for a package's own web UI (e.g. picoclaw on port 18800). To
reach one from another machine, widen it with `--bind`; if a proxy is already
forwarding that port, this updates it in place rather than erroring out:

```bash
# Reachable from any interface on the host
ailab port add mybox 18800 --bind 0.0.0.0

# Reachable only from a specific address (e.g. the host's public IP)
ailab port add mybox 18800 --bind 203.0.113.10

# Narrow it back to loopback-only
ailab port remove mybox 18800
```

Only do this on a network you trust — it makes the container's service
reachable to anyone who can reach that address, with none of the
token-based auth the web dashboard has.

## Installable Packages

Packages install as classic-confinement snaps from the
[nimbus-app-store](https://github.com/kenvandine/nimbus-app-store) catalog —
the same catalog the [Nimbus](https://github.com/kenvandine/nimbus-appliance)
appliance uses. `ailab install` fetches the catalog live, `snap install`s the
package, forwards the ports it declares, and runs its onboarding/post-install
steps.

| Package | Status | Description |
|---------|--------|-------------|
| `openclaw` | Supported | AI coding agent with local-first LLM support. Web UI at `http://127.0.0.1:18789`. |
| `nullclaw` | Experimental | Lightweight static-binary AI agent gateway (Zig-built). Web UI at `http://127.0.0.1:3002`. |
| `picoclaw` | Supported | Ultra-lightweight Go-based AI agent gateway (30+ providers). Web UI at `http://127.0.0.1:18800`. |
| `hermes-agent` | Experimental | Autonomous AI agent, 60+ built-in tools, 20+ platform integrations. Web UI at `http://127.0.0.1:9119`. |
| `odysseus` | Experimental | Self-hosted AI workspace (chat, documents, research). Web UI at `http://127.0.0.1:7000`. |
| `zeroclaw` | Experimental | Zero-config autonomous AI agent. Web UI at `http://127.0.0.1:3000`. |

Every package uses lemonade-server as its primary provider via its
OpenAI-compatible API, auto-detected on `localhost:13305` (>= 10.1) or
`localhost:8000` (< 10.1), and most also configure ollama on
`localhost:11434` as a secondary provider — each snap's own onboarding tool
(`<package>.lemonade --auto`) handles this during install.

## How It Works

```
Your Host
├── lemonade-server :13305 (>= 10.1) or :8000 (< 10.1)
├── ollama          :11434
└── ailab container (LXD, privileged — required for classic snap confinement)
    ├── localhost:13305  →  host:13305  (lemonade >= 10.1, inbound proxy)
    ├── localhost:8000   →  host:8000   (lemonade < 10.1,  inbound proxy)
    └── localhost:11434  →  host:11434  (ollama, inbound proxy)
```

Package-specific ports (e.g. openclaw :18789) come from that package's entry
in the nimbus-app-store catalog and are forwarded when the package is
installed, not at container creation time.

**LXD REST API**: All container operations use the LXD REST API via `pylxd`,
not the `lxc` CLI. Container setup runs via cloud-init at creation time,
so no restart is needed and configuration is applied atomically.

**LXD project**: All containers are created inside the `ailab` LXD project,
keeping them separate from any other LXD containers on your system. You can
see them with `lxc --project ailab list`.

**Home directory**: Each container gets an isolated home directory —
`~/ailab/<name>` on the host (or under the snap's data directory for snap
installs) — bind-mounted at your home path inside the container using
`raw.idmap` for correct UID/GID passthrough. The container sees only this
directory, not your real home; files you create inside it appear on the host
under `~/ailab/<name>` and vice versa.

**Per-container config**: Each container has an isolated home directory, so
tool configs (e.g. `~/.openclaw/openclaw.json`) are automatically per-container.
You can have two containers running the same tool with different configurations.

**Privileged + nesting**: Containers are created with `security.nesting=true`
(docker, fuse, and other tools that need kernel features inside the
container) and `security.privileged=true` plus syscall interception for
`mknod`/`setxattr`. The latter are required for `snap install --classic` to
work inside the container — classic-confinement snaps rely on bind-mount
tricks that only a privileged container can perform. Containers created
before this was added need to be recreated (`ailab delete` + `ailab new`)
before packages can be installed.

## Security model

AI Lab's goal is to keep AI tools — and whatever they install or download —
off your host system and out of your real home directory. It is **not** a
hard security sandbox for running actively malicious code. Understand these
boundaries before pointing an autonomous agent at anything sensitive.

**What AI Lab protects**

- **Your host packages and system.** Tools install *inside* the container
  (snaps, npm, pip, brew), never on your host.
- **Your real home directory.** Each container only sees its own isolated
  home (`~/ailab/<name>` on the host), not the rest of `~`. A tool that
  `rm -rf`s its home only affects that one container's directory.
- **Other containers.** Each has its own home and config, and all live in a
  dedicated `ailab` LXD project separate from your other LXD instances.
- **The management API.** Every `/api` route, including the interactive shell
  and log WebSockets, requires the bearer token from `ailab dashboard`. The
  web daemon binds `127.0.0.1` by default, and cross-origin browser pages are
  rejected even if they somehow obtain the token.

**What AI Lab does *not* protect against**

- **Container escape.** ailab containers run **privileged**
  (`security.privileged=true`), which is *required* for classic-confinement
  snaps like openclaw to install. Privileged container root is effectively
  host root: a determined attacker who gains root inside the container may be
  able to escape to the host. Treat the container as a convenience/tidiness
  boundary, not a VM-grade trust boundary. Do not run code you actively
  distrust and expect the host to be safe.
- **Your files, if you widen the mount.** Only `~/ailab/<name>` is exposed by
  default; anything you additionally bind-mount or forward is on you.
- **Anyone who can reach a widened bind.** `ailab web --host 0.0.0.0` (or
  `snap set ailab web.host=0.0.0.0`) exposes the token-protected API to the
  network — only do this on a trusted network.
- **Supply chain.** Container provisioning and package onboarding fetch and
  run scripts from the network (Node.js, bun, Homebrew, the nimbus-app-store
  catalog). These run inside the container, but they are not pinned or
  checksum-verified.

**Access notes**

- The web daemon runs as **root** under the snap (it needs the LXD socket) and
  stores its token `0600` under the snap's data directory; use
  `sudo ailab dashboard` to read it.
- Non-snap installs need your user in the `lxd` group; that group grants full
  control of LXD, which is itself root-equivalent. `ailab doctor` checks this.

## Outbound Ports

ailab doesn't forward any ports by default at container-creation time.
Package-specific ports come from that package's entry in the
nimbus-app-store catalog and are forwarded automatically when you run
`ailab install <name> <package>` — see the
[Installable Packages](#installable-packages) table above for each
package's port. You can forward additional ports yourself with
`ailab port add`.

When multiple containers are running, ailab automatically skips proxy devices
whose host port is already bound, so containers can start without conflicts.
Conflicting proxies are restored to the config so they activate once the port
is freed.

## Cloud Access

AI Lab Cloud lets you access your home containers from any browser, anywhere
— no VPN or port forwarding required. A lightweight tunnel client runs
alongside the web daemon, opening an outbound connection to a hub you
self-host on a VPS.

Keep `ailab` and `ailab-cloud` in step when deploying tunnel-related changes.
The client and hub are developed together, so protocol or registration changes
should be rolled out as a matched pair.

### How it works

```
Browser (anywhere)  ──HTTPS──►  AI Lab Cloud Hub (your VPS)
                                        │
                               WebSocket tunnel
                               (outbound from home)
                                        │
                               AI Lab (your home machine)
                                        │
                               LXD proxy device
                                        │
                               Container: openclaw / nullclaw / etc.
```

The hub authenticates your browser via GitHub OAuth and routes traffic only
to the tunnel registered by the matching GitHub user.

### Quick setup

**1. Deploy the hub** on a VPS with a single snap install — Redis, Caddy
(TLS), and the hub API are all bundled. Full instructions are in the
[AI Lab Cloud README](https://github.com/lemonade-sdk/ailab-cloud).

**2. Get your tunnel token.** Log in to your hub in a browser, then visit:
```
https://cloud.example.com/auth/tunnel-token
```

**3. Configure AI Lab on your home machine:**

```bash
sudo snap set ailab cloud.enabled=true
sudo snap set ailab cloud.host=https://cloud.example.com
sudo snap set ailab cloud.user=yourname
sudo snap set ailab cloud.token=<token from step 2>
sudo snap set ailab cloud.device-id=myhome   # lowercase letters, digits, and hyphens only
sudo snap restart ailab.web
```

`cloud.host` accepts either `cloud.example.com` or `https://cloud.example.com`,
but the full URL is the recommended form.

**4. Visit** `https://myhome.cloud.example.com` from any browser and log
in with GitHub. The full AI Lab dashboard loads proxied through the tunnel,
including the interactive terminal and all "Open …" buttons for installed
tools.

### Cloud settings reference

| Setting | Description |
|---|---|
| `cloud.enabled` | Set to `true` to start the tunnel client (default: `false`) |
| `cloud.host` | Hub URL or hostname, e.g. `https://cloud.example.com` |
| `cloud.user` | Your GitHub username (must match your hub login) |
| `cloud.token` | Tunnel token from `/auth/tunnel-token` on the hub |
| `cloud.device-id` | Short identifier for this machine; use lowercase letters, digits, and hyphens only |
| `cloud.ports` | Comma-separated local ports to expose through the tunnel (default: `11500`; add `18789` for openclaw and any other tool ports you want reachable remotely) |

```bash
snap get ailab cloud   # view all cloud settings at once
```

Disable cloud access without losing the settings:

```bash
sudo snap set ailab cloud.enabled=false
sudo snap restart ailab.web
```

---

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

**Reinstalling a package**: Just re-run `ailab install`. `snap install` is a
no-op if the package is already installed (snapd's usual `snap refresh`
handles picking up new versions), but the onboard command and post-install
script both re-run, so it's an easy way to refresh a package's config.

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
