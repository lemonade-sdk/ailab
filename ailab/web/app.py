"""FastAPI web management interface for ailab."""

import asyncio
import fcntl
import io
import json
import os
import pty
import struct
import sys
import termios
from pathlib import Path
from typing import Any

import pylxd.exceptions

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ailab.container import (
    AILAB_PROJECT,
    _client,
    _container_name,
    _container_status,
    _current_user,
    _get_instance,
    _host_port_in_use,
    _partition_conflicting_proxies,
    _user_info,
    add_port,
    add_proxy_device,
    build_shell_welcome,
    container_config_dir,
    container_exec,
    create_container,
    delete_container,
    get_container_user,
    has_device,
    list_ports,
    list_system_users,
    remove_port,
    remove_proxy_device,
    start_container,
    stop_container,
    OUTBOUND_PROXIES,
)
from ailab.installers import INSTALLERS, get_installer
from ailab.installers.openclaw import (
    OPENCLAW_GATEWAY_PORT,
    OpenclawInstaller,
)

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="ailab web interface")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"

# ── Request/response models ───────────────────────────────────────────────────


class CreateContainerRequest(BaseModel):
    name: str
    packages: list[str] = []
    extra_ports: list[dict[str, Any]] = []
    username: str | None = None


class InstallRequest(BaseModel):
    package: str


class AddPortRequest(BaseModel):
    host_port: int
    container_port: int
    direction: str = "outbound"


# ── Helpers ───────────────────────────────────────────────────────────────────


# _get_container_user is imported from ailab.container as get_container_user;
# alias it for local use throughout this module.
_get_container_user = get_container_user


def _get_ipv4(client, cname: str) -> str:
    """Return the first non-loopback IPv4 for a container."""
    try:
        state = client.instances.get(cname).state()
        for iface in (state.network or {}).values():
            for addr in iface.get("addresses", []):
                if addr["family"] == "inet" and not addr["address"].startswith("127."):
                    return addr["address"]
    except Exception:
        pass
    return ""


def _outbound_ports_from_devices(devices: dict) -> list[int]:
    """Extract outbound proxy port numbers from expanded_devices."""
    ports = []
    for cfg in devices.values():
        if (
            cfg.get("type") == "proxy"
            and cfg.get("bind", "host") == "host"
            and ":" in cfg.get("listen", "")
        ):
            try:
                ports.append(int(cfg["listen"].rsplit(":", 1)[-1]))
            except ValueError:
                pass
    return sorted(ports)


def _container_summary(c: dict, client) -> dict:
    """Build the summary dict for a single container metadata entry."""
    cname = c["name"]
    mapped_user = c.get("config", {}).get("user.ailab-mapped-user")
    if mapped_user:
        try:
            _, _, _, home = _user_info(mapped_user)
        except KeyError:
            _, _, _, home = _current_user()
    else:
        _, _, _, home = _current_user()
    devices = c.get("expanded_devices", {})
    return {
        "name": cname,
        "status": c.get("status", "unknown"),
        "ipv4": _get_ipv4(client, cname),
        "outbound_ports": _outbound_ports_from_devices(devices),
        "config_dir": str(container_config_dir(cname, home)),
    }


def _sse_response(gen):
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _lxd_error(exc: Exception) -> HTTPException:
    """Convert a pylxd exception into an appropriate HTTPException."""
    if isinstance(exc, pylxd.exceptions.NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, pylxd.exceptions.LXDAPIException):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _sse_stream(task_fn):
    """
    Return a StreamingResponse that runs task_fn() in a thread executor,
    capturing print() output as SSE log events.
    """
    async def generate():
        queue: asyncio.Queue[dict] = asyncio.Queue()
        old_stdout = sys.stdout

        class SSECapture(io.TextIOBase):
            def write(self, s):
                if s.strip():
                    queue.put_nowait({"type": "log", "msg": s.rstrip()})
                return len(s)

        sys.stdout = SSECapture()

        async def run_task():
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, task_fn)
                await queue.put({"type": "done"})
            except Exception as exc:
                await queue.put({"type": "error", "msg": str(exc)})
            finally:
                sys.stdout = old_stdout

        asyncio.create_task(run_task())

        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event["type"] in ("done", "error"):
                break

    return _sse_response(generate())


# ── Container endpoints ───────────────────────────────────────────────────────


@app.get("/api/containers")
async def api_list_containers():
    client = _client()
    resp = client.api.instances.get(params={"recursion": "1"})
    containers = resp.json().get("metadata", [])
    loop = asyncio.get_event_loop()
    results = await asyncio.gather(
        *[loop.run_in_executor(None, _container_summary, c, client) for c in containers]
    )
    return list(results)


@app.get("/api/containers/{name}")
async def api_get_container(name: str):
    cname = _container_name(name)
    client = _client()
    try:
        instance = _get_instance(cname)
    except pylxd.exceptions.NotFound:
        raise HTTPException(status_code=404, detail=f"Container '{name}' not found")
    ipv4 = await asyncio.get_event_loop().run_in_executor(None, _get_ipv4, client, cname)

    devices = instance.expanded_devices or {}
    outbound = []
    inbound = []
    for dev_name, cfg in devices.items():
        if cfg.get("type") != "proxy":
            continue
        listen = cfg.get("listen", "")
        connect = cfg.get("connect", "")
        bind = cfg.get("bind", "host")
        entry = {
            "device": dev_name,
            "listen": listen,
            "connect": connect,
            "direction": "inbound" if bind == "instance" else "outbound",
        }
        if bind == "instance":
            inbound.append(entry)
        else:
            outbound.append(entry)

    return {
        "name": cname,
        "status": instance.status,
        "ipv4": ipv4,
        "config": dict(instance.config or {}),
        "devices": devices,
        "outbound_ports": outbound,
        "inbound_ports": inbound,
    }


@app.post("/api/containers/create")
async def api_create_container(req: CreateContainerRequest):
    extra_ports = []
    for spec in req.extra_ports:
        try:
            extra_ports.append((int(spec["host_port"]), int(spec["container_port"])))
        except (KeyError, ValueError):
            pass

    packages = req.packages or []

    def task():
        create_container(req.name, extra_outbound_ports=extra_ports or None, username=req.username or None)
        for pkg_name in packages:
            installer = get_installer(pkg_name)
            print(f"\nInstalling {pkg_name}...")
            installer.install(req.name)

    return _sse_stream(task)


@app.post("/api/containers/{name}/start")
async def api_start_container(name: str):
    cname = _container_name(name)
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, start_container, cname)
    except (pylxd.exceptions.LXDAPIException, pylxd.exceptions.NotFound) as exc:
        raise _lxd_error(exc)
    return {"status": "started", "name": name}


@app.post("/api/containers/{name}/stop")
async def api_stop_container(name: str):
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, stop_container, name)
    except (pylxd.exceptions.LXDAPIException, pylxd.exceptions.NotFound) as exc:
        raise _lxd_error(exc)
    return {"status": "stopped", "name": name}


@app.delete("/api/containers/{name}")
async def api_delete_container(name: str):
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: delete_container(name, force=True))
    except (pylxd.exceptions.LXDAPIException, pylxd.exceptions.NotFound) as exc:
        raise _lxd_error(exc)
    return {"status": "deleted", "name": name}


@app.post("/api/containers/{name}/install")
async def api_install_package(name: str, req: InstallRequest):
    def task():
        installer = get_installer(req.package)
        installer.install(name)

    return _sse_stream(task)


# ── Port endpoints ────────────────────────────────────────────────────────────


@app.get("/api/containers/{name}/ports")
async def api_list_ports(name: str):
    cname = _container_name(name)
    instance = _get_instance(cname)
    devices = instance.expanded_devices or {}
    ports = []
    for dev_name, cfg in devices.items():
        if cfg.get("type") != "proxy":
            continue
        bind = cfg.get("bind", "host")
        ports.append({
            "device": dev_name,
            "direction": "inbound" if bind == "instance" else "outbound",
            "listen": cfg.get("listen", ""),
            "connect": cfg.get("connect", ""),
        })
    return ports


@app.post("/api/containers/{name}/ports")
async def api_add_port(name: str, req: AddPortRequest):
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None, add_port, name, req.host_port, req.container_port, req.direction
        )
    except (pylxd.exceptions.LXDAPIException, pylxd.exceptions.NotFound) as exc:
        raise _lxd_error(exc)
    return {"status": "added", "host_port": req.host_port, "container_port": req.container_port}


@app.delete("/api/containers/{name}/ports/{device_name}")
async def api_remove_port(name: str, device_name: str):
    cname = _container_name(name)
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, remove_proxy_device, cname, device_name)
    except (pylxd.exceptions.LXDAPIException, pylxd.exceptions.NotFound) as exc:
        raise _lxd_error(exc)
    return {"status": "removed", "device": device_name}


# ── Gateway URL + pair endpoints ──────────────────────────────────────────────

def _read_gateway_token(cfg_dir: Path) -> str | None:
    """Read the gateway shared token from openclaw.json (used in the dashboard URL).

    The dashboard URL format is http://localhost:18789/#token=<GATEWAY_SHARED_TOKEN>.
    This is the gateway auth token stored under gateway.auth.token in openclaw.json.
    Only present once openclaw has been onboarded.
    """
    openclaw_json = cfg_dir / "openclaw.json"
    if not openclaw_json.exists():
        return None
    try:
        data = json.loads(openclaw_json.read_text())
        return data.get("gateway", {}).get("auth", {}).get("token")
    except Exception:
        return None


def _get_or_create_gateway_token(cfg_dir: Path, home: str) -> str:
    """Return the existing gateway shared token from environment.d, or generate a new one."""
    import secrets as _secrets
    env_conf = Path(home) / ".config" / "environment.d" / "ailab-openclaw.conf"
    if env_conf.exists():
        for line in env_conf.read_text().splitlines():
            if line.startswith("OPENCLAW_GATEWAY_TOKEN="):
                return line.split("=", 1)[1].strip()
    return _secrets.token_urlsafe(32)


@app.get("/api/containers/{name}/gateway-url")
async def api_gateway_url(name: str):
    """Return the openclaw dashboard URL with device token, if the container has openclaw."""
    cname = _container_name(name)
    _, _, _, home = _get_container_user(cname)
    cfg_dir = container_config_dir(name, home) / "openclaw"
    token = _read_gateway_token(cfg_dir)
    if not token:
        raise HTTPException(status_code=404, detail="openclaw device token not found")
    return {"url": f"http://localhost:{OPENCLAW_GATEWAY_PORT}/#token={token}"}


@app.post("/api/containers/{name}/gateway-pair")
async def api_gateway_pair(name: str):
    """Run openclaw onboard inside the container to pair the gateway device."""
    cname = _container_name(name)
    if _container_status(cname) != "running":
        raise HTTPException(status_code=409, detail=f"Container '{name}' is not running")

    username, uid, gid, home = _get_container_user(cname)
    cfg_dir = container_config_dir(name, home) / "openclaw"

    if not (cfg_dir / "openclaw.json").exists():
        raise HTTPException(status_code=409, detail="openclaw is not installed in this container")

    installer = OpenclawInstaller()

    def task():
        gateway_token = _get_or_create_gateway_token(cfg_dir, home)
        print("Configuring gateway environment...")
        installer._configure_gateway_env(cname, uid, gid, home, cfg_dir, gateway_token)
        print("Pairing gateway device (this takes ~10 seconds)...")
        installer._run_onboard(cname, uid, gid, home, cfg_dir, gateway_token)
        token = _read_gateway_token(cfg_dir)
        if token:
            print(f"Paired! Dashboard: http://localhost:{OPENCLAW_GATEWAY_PORT}/#token={token}")
        else:
            print("Warning: pairing may not have succeeded — check container logs")

    return _sse_stream(task)



# ── Packages endpoint ─────────────────────────────────────────────────────────

@app.get("/api/packages")
async def api_list_packages():
    return [
        {"name": name, "description": cls().description}
        for name, cls in sorted(INSTALLERS.items())
    ]


@app.get("/api/users")
async def api_list_users():
    """Return host users with UID >= 1000 (candidates for container mapping)."""
    return list_system_users()


# ── WebSocket: PTY shell ──────────────────────────────────────────────────────


@app.websocket("/api/ws/shell/{name}")
async def shell_ws(ws: WebSocket, name: str):
    await ws.accept()
    cname = _container_name(name)
    username, uid, gid, home = _get_container_user(cname)
    cmd = [
        "lxc", "--project", AILAB_PROJECT, "exec", cname,
        f"--user={uid}", f"--group={gid}",
        f"--env=HOME={home}", f"--env=USER={username}",
        f"--env=LOGNAME={username}",
        f"--env=XDG_RUNTIME_DIR=/run/user/{uid}",
        f"--env=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
        "--env=TERM=xterm-256color",
        f"--env=SHELL_WELCOME={build_shell_welcome(name)}",
        f"--cwd={home}", "--", "/bin/bash", "--login",
    ]

    master_fd, slave_fd = pty.openpty()
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)
    loop = asyncio.get_event_loop()

    async def pty_reader():
        while True:
            try:
                data = await loop.run_in_executor(None, lambda: os.read(master_fd, 4096))
                await ws.send_bytes(data)
            except (OSError, WebSocketDisconnect):
                break

    async def ws_reader():
        while True:
            try:
                msg = await ws.receive()
                if "bytes" in msg:
                    os.write(master_fd, msg["bytes"])
                elif "text" in msg:
                    data = json.loads(msg["text"])
                    if data.get("type") == "resize":
                        cols, rows = int(data["cols"]), int(data["rows"])
                        fcntl.ioctl(
                            master_fd, termios.TIOCSWINSZ,
                            struct.pack("HHHH", rows, cols, 0, 0),
                        )
            except (WebSocketDisconnect, Exception):
                break

    try:
        await asyncio.gather(pty_reader(), ws_reader(), return_exceptions=True)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            proc.terminate()
        except Exception:
            pass


# ── WebSocket: log tail ───────────────────────────────────────────────────────


@app.websocket("/api/ws/logs/{name}")
async def logs_ws(ws: WebSocket, name: str):
    await ws.accept()
    cname = _container_name(name)
    proc = await asyncio.create_subprocess_exec(
        "lxc", "--project", AILAB_PROJECT, "exec", cname, "--",
        "journalctl", "-f", "-n", "50", "--no-pager",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        async for line in proc.stdout:
            await ws.send_text(line.decode(errors="replace").rstrip())
    except WebSocketDisconnect:
        pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


# ── Static file serving / SPA fallback ───────────────────────────────────────

if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"error": "Frontend not built. Run: cd frontend && npm run build"}
