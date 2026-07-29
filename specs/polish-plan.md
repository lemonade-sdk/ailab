# AI Lab polish plan — review findings and phased work

Comprehensive review (2026-07-28) of ailab on branch `nimbus-appstore`, focused on
making it the best, easiest, and most secure way to run AI agents (openclaw,
hermes, etc.) in LXD containers — CLI + web, installed as a strict snap.

Note: privileged containers are **required** for classic-confinement snaps
(snap-confine's bind-mount tricks), so the "unprivileged containers"
investigation is intentionally **skipped** — instead, document the threat model
honestly.

## Review findings

### 🔴 Security

1. **Web API and WebSocket shell have zero authentication.**
   - `CORSMiddleware(allow_origins=["*"], allow_credentials=True)`
     (`web/app.py`) lets any website read API responses cross-origin.
   - WebSockets are not subject to CORS: a drive-by web page can open
     `ws://127.0.0.1:11500/api/ws/shell/<name>` and get an interactive shell
     in a privileged container. No Origin check on `shell_ws` / `logs_ws`.
   - `ailab web` CLI default is `--host ::` (all interfaces) while README
     claims 127.0.0.1. (Snap wrapper defaults to 127.0.0.1; bare CLI doesn't.)

2. **Cross-user privilege escalation via `username`.**
   `POST /api/containers/create` accepts any `username`; `/api/users` lists
   candidates, unauthenticated. Daemon runs as root → any local user (or any
   website per #1) can create a container mapped to another user's uid and
   shell into it.

3. **Privileged containers are not a security boundary** but README says
   "Safe by default". Required for classic snaps, so keep — but document the
   threat model honestly. The isolated per-container home
   (`~/ailab/<name>` only, not the full home) is the real mitigation; README
   lines still claim the full home is shared (wrong and scarier than reality).

4. **Runtime `curl | bash` supply chain**: cloud-init pipes bun/homebrew/
   nodesource installers; catalog post-install scripts fetched from a branch
   head, unpinned. Contained to the container; future: pinning/checksums.

5. **Invalid cloud settings crash-loop the daemon.** `CloudConfig.from_env()`
   raises inside FastAPI lifespan → uvicorn dies → restart loop. The configure
   hook validates `web.*` but not `cloud.*`.

### 🟠 Correctness bugs

| Where | Bug |
|---|---|
| `container.py` ~1088 | "Remove conflicting proxy devices" loop is a no-op — both branches identical. Creation does NOT skip in-use ports (README says it does). |
| `web/app.py` (2 places) | Inbound/outbound classification checks `bind == "instance"`, but devices use `bind: "container"` — inbound proxies misreported as outbound. |
| `container.py` welcome | Says `ailab install openclaw <name>` — args reversed. |
| `web/app.py` `_sse_stream` | Swaps global `sys.stdout`; concurrent operations interleave logs and restore stdout under each other. Needs per-task capture (contextvar). |
| `cli.py` `cmd_web` | `--reload` can't work with `uvicorn.run(app_object)`; needs import string. |
| `cli.py` `_complete` | `commands` list omits `web`. |
| `container.py` `_host_port_in_use` | Uses `bind()`; CLI app plug set lacks `network-bind` — verify under strict confinement (if denied, every port looks in use). |
| `container.py` `list_containers` | One state round-trip per container — slow. Also in web `_container_summary`. |

### 🟡 CLI / UX gaps

- No `ailab doctor` / first-run diagnostics (LXD missing, not initialised,
  interface not connected, lxd group, lemonade not running → raw tracebacks).
- No `ailab info`, `ailab logs`; no CLI parity for gateway URL (print
  tokenized dashboard URL after install).
- `ailab packages` shows only the static fallback table, not the live catalog.
- Man page / completions stale; no zsh/fish completions.

### 🟡 Snap / packaging / CI

- No `icon:` or store assets in snapcraft.yaml.
- No snap build or install smoke test in CI (only deb/lintian).
- README/QUICKSTART drift: home-sharing claims, web bind default, "skips
  conflicting proxies at creation".
- No unit tests. Cheap targets: `appstore.py`, `_partition_conflicting_proxies`,
  `CloudConfig._normalize_ports`, CLI parser. LXD integration job feasible.

### 🟢 Already good — keep

Catalog-driven installers with live-catalog-first resolution; isolated
per-container homes; cloud-init atomic provisioning; SSE keepalives; tunnel
port allowlisting + header hygiene; sticky-bit SNAP_COMMON layout; the real
port-conflict restore logic in `start_container`.

## Phases

### Phase 0 — Security hardening  ✅ DONE (2026-07-28, unreleased)
1. Token auth for web API + WebSockets. Token generated/persisted under
   SNAP_COMMON at daemon start; required on every `/api/*` route and WS
   handshake; frontend gets it via `#token=…` URL (printed by CLI/snap).
   Origin allowlist on WS endpoints.
2. Drop wildcard CORS; allow only own origin + tunnel origin.
3. `ailab web` CLI default → 127.0.0.1; wide binds need explicit flag.
4. Lock down `username` mapping (only for authenticated/admin callers).
5. Validate `cloud.*` in configure hook; `from_env` failures log-and-disable
   instead of crash-looping.

### Phase 1 — Correctness fixes  ✅ DONE (2026-07-28, unreleased)
All bugs in the table above. Notes:
- Auth lives in `ailab/web/auth.py` (ASGI middleware, covers HTTP + WS);
  token file `web-token` under SNAP_COMMON / XDG data dir, 0600.
- Tunnel client injects the local bearer token for the web port
  (`CloudTunnelManager(web_auth=(port, token))`); remote users authenticate
  via the hub's GitHub OAuth.
- New CLI command: `ailab dashboard` (prints tokenized URL; sudo under snap).
- `_sse_stream` now routes print() through a contextvar-keyed stdout proxy;
  pylxd stream handlers are context-bound in `container.py` because pylxd
  invokes them from its own websocket threads.
- `_host_port_in_use` switched bind()→connect_ex() so it works with only the
  `network` plug under strict confinement.
- Heads-up: ruff ≥0.16 broadened its default rule set; CI's bare
  `ruff check ailab/` may start failing on pre-existing style issues.
  Pin ruff or set an explicit `[tool.ruff]` select in Phase 5.

### ~~Phase 2 — Unprivileged containers~~  SKIPPED
Privileged is required for classic snaps. Instead: honest threat-model docs.

### Phase 3 — CLI intuitiveness  ✅ DONE (2026-07-28, unreleased)
- New `ailab/doctor.py`: `run_checks()` (full report) + `preflight()`
  (LXD-critical subset, raises `DoctorError`). Checks LXD socket, API
  connectivity (classifies permission errors → snap interface vs lxd
  group), storage/network init, ailab project, lemonade + ollama.
- `create_container` calls `preflight()` (lazy import to avoid a cycle);
  `main()` catches `DoctorError` → clean stderr message, exit 1. Web path
  surfaces it via the SSE error event.
- `ailab info <name>`: status, IP, mapped user, config dir, in/out ports,
  installed catalog apps (via `snap list` when running), openclaw
  tokenized dashboard URL.
- `ailab logs <name> [-f] [-n N]`: journalctl tail/follow via container_exec
  stream; friendly error when stopped/missing.
- `ailab packages`: live nimbus-app-store catalog with ports; falls back to
  the built-in table when the catalog is unreachable.
- Post-install: `CatalogAppInstaller.post_install_hints()` hook; openclaw
  prints its `#token=` dashboard URL after install (CLI + web SSE log).
- Man page (debian/ailab.1) + bash completion updated for doctor/info/logs/
  web/dashboard; fixed stale full-home-share and config-dir claims.
- Note: pylxd 2.4.1 emits harmless "unknown attribute" UserWarnings when
  reading newer-LXD profiles/projects (pre-existing, not Phase 3). Consider
  suppressing in Phase 5.

### Phase 4 — Web UX  ✅ DONE (2026-07-28, unreleased)
Port-direction display + concurrent-safe progress logs were already fixed in
Phase 1, and the token login flow / locked screen in Phase 0. Remaining work:
- New `GET /api/host-status`: lemonade (reachable + port), ollama, and cloud
  tunnel state (configured/connected/host/device). `CloudTunnelManager` gained
  `connected`/`host`/`device_id` properties; the manager is stashed in an
  app-module global from lifespan so the endpoint can read live state.
- `HostStatus` header strip (frontend) polls every 10s and shows a dot per
  service; the cloud dot only appears when a tunnel is configured. Hidden on
  the locked screen and narrow viewports.
- Toast system: `frontend/src/toast.ts` (pub/sub store, no context) +
  `Toaster` component. Replaced the disruptive `alert()` calls in
  ContainerList (start/stop/delete) with toasts; delete shows a success toast.
  Modal-inline errors (Create/Install/Port/ChangeModel) were already good UX
  and left as-is. Periodic list refresh stays console.error to avoid a toast
  storm when the daemon is briefly unreachable.

### Phase 5 — Packaging, CI, docs  ✅ DONE (2026-07-28, unreleased)
- Unit tests under `tests/` (50): appstore parsing, port partitioning +
  sort key, CloudConfig normalize/from_env, auth (origin allowlist, token
  file perms, middleware 401/pass-through incl. foreign-origin reject),
  doctor formatting/classification, CLI parser. `[tool.pytest.ini_options]`
  + `[project.optional-dependencies] test` in pyproject.
- CI: new `unit` job (pytest) and `snap` job (snapcraft build via
  snapcore/action-build, `snap install --dangerous`, smoke `ailab --version
  / --help / packages`, upload artifact). Snap job needs fetch-depth: 0 for
  `git describe --tags`.
- Snap icon: `snap/gui/ailab.svg` (lemon on dark rounded square), referenced
  via `icon:` in snapcraft.yaml.
- Docs: new "Security model" section in README (what it protects vs. not —
  privileged containers are NOT a hard boundary; isolated home; token auth;
  widened-bind and supply-chain caveats); `ailab doctor` added to setup steps.
- Quieted pylxd 2.4.x "unknown attribute" UserWarnings via a targeted
  `warnings.filterwarnings` in container.py.
- Not done (deferred, lower value): a full LXD end-to-end integration job in
  CI (the snap smoke job covers build+install+CLI; container-lifecycle
  integration would need an LXD-enabled runner and is better as a manual/
  nightly job).
