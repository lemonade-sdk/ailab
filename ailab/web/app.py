"""FastAPI web management interface for ailab."""

import asyncio
import io
import json
import logging
import socket as _socket
import sys
import time as _time
import urllib.error as _urllib_error
import urllib.request as _urllib_request
from pathlib import Path
from typing import Any

import aiohttp
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
    _find_lxd_socket,
    _get_instance,
    _user_info,
    add_port,
    build_shell_welcome,
    container_config_dir,
    container_exec,
    create_container,
    delete_container,
    get_container_user,
    list_system_users,
    pull_file,
    push_file,
    remove_proxy_device,
    start_container,
    stop_container,
)
from ailab.installers import INSTALLERS, get_installer
from ailab.installers.openclaw import (
    OPENCLAW_GATEWAY_PORT,
    OpenclawInstaller,
)

# ── App setup ─────────────────────────────────────────────────────────────────

logger = logging.getLogger("ailab.web")

# ── Lemonade recipes cache ────────────────────────────────────────────────────

_RECIPES_GITHUB_API = (
    "https://api.github.com/repos/kenvandine/recipes/contents/openclaw"
    "?ref=openclaw_recipes"
)
_RECIPES_CACHE_TTL = 300  # 5 minutes
_recipes_cache: list | None = None
_recipes_cache_ts: float = 0.0


def _detect_lemonade_port() -> int | None:
    """Return the first reachable lemonade-server port (13305 or 8000), or None."""
    for port in [13305, 8000]:
        try:
            with _socket.create_connection(("127.0.0.1", port), timeout=2):
                return port
        except OSError:
            pass
    return None

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


class ImportRecipeRequest(BaseModel):
    recipe: dict


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
        loop = asyncio.get_running_loop()
        old_stdout = sys.stdout

        class SSECapture(io.TextIOBase):
            def write(self, s):
                if s.strip():
                    # Must use call_soon_threadsafe: write() is called from a
                    # thread-pool worker, but asyncio.Queue is not thread-safe.
                    loop.call_soon_threadsafe(
                        queue.put_nowait, {"type": "log", "msg": s.rstrip()}
                    )
                return len(s)

        sys.stdout = SSECapture()

        async def run_task():
            try:
                await loop.run_in_executor(None, task_fn)
                await queue.put({"type": "done"})
            except Exception as exc:
                await queue.put({"type": "error", "msg": str(exc)})
            finally:
                sys.stdout = old_stdout

        asyncio.create_task(run_task())

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20)
            except asyncio.TimeoutError:
                # Send a keepalive comment so the browser doesn't close the
                # connection during long silent operations (e.g. npm install).
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(event)}\n\n"
            if event["type"] in ("done", "error"):
                break

    return _sse_response(generate())


# ── Container endpoints ───────────────────────────────────────────────────────


@app.get("/api/containers")
async def api_list_containers():
    def _fetch():
        client = _client()
        resp = client.api.instances.get(params={"recursion": "1"})
        containers = resp.json().get("metadata", [])
        return [_container_summary(c, client) for c in containers]
    return await asyncio.to_thread(_fetch)


@app.get("/api/containers/{name}")
async def api_get_container(name: str):
    cname = _container_name(name)

    def _fetch():
        client = _client()
        try:
            instance = _get_instance(cname)
        except pylxd.exceptions.NotFound:
            return None
        ipv4 = _get_ipv4(client, cname)

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

    result = await asyncio.to_thread(_fetch)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Container '{name}' not found")
    return result


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

    def _fetch():
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

    return await asyncio.to_thread(_fetch)


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

def _read_gateway_token(token_dir: Path) -> str | None:
    """Read the gateway shared token from the host-side gateway-token file.

    token_dir is container_config_dir(name, home) / "openclaw" — a directory
    created by the installer process with host-owned permissions, readable by
    the snap web service regardless of LXD subuid ownership.
    """
    token_file = token_dir / "gateway-token"
    if token_file.exists():
        token = token_file.read_text().strip()
        if token:
            return token
    return None


def _get_or_create_gateway_token(token_dir: Path) -> str:
    """Return the existing gateway shared token, or generate a new one."""
    import secrets as _secrets
    token = _read_gateway_token(token_dir)
    if token:
        return token
    return _secrets.token_urlsafe(32)


@app.get("/api/containers/{name}/gateway-url")
async def api_gateway_url(name: str):
    """Return the openclaw dashboard URL with device token, if the container has openclaw."""
    cname = _container_name(name)
    _, _, _, home = await asyncio.to_thread(_get_container_user, cname)
    token_dir = container_config_dir(name, home) / "openclaw"
    token = _read_gateway_token(token_dir)
    if not token:
        raise HTTPException(status_code=404, detail="openclaw device token not found")
    return {"url": f"http://localhost:{OPENCLAW_GATEWAY_PORT}/#token={token}"}


@app.post("/api/containers/{name}/gateway-pair")
async def api_gateway_pair(name: str):
    """Run openclaw onboard inside the container to pair the gateway device."""
    cname = _container_name(name)
    status = await asyncio.to_thread(_container_status, cname)
    if status != "running":
        raise HTTPException(status_code=409, detail=f"Container '{name}' is not running")

    username, uid, gid, home = await asyncio.to_thread(_get_container_user, cname)
    token_dir = container_config_dir(name, home) / "openclaw"

    if not (token_dir / "gateway-token").exists():
        raise HTTPException(status_code=409, detail="openclaw is not installed in this container")

    installer = OpenclawInstaller()

    def task():
        gateway_token = _get_or_create_gateway_token(token_dir)
        # Refresh the host-side token file in case it was regenerated.
        token_dir.mkdir(parents=True, exist_ok=True)
        (token_dir / "gateway-token").write_text(gateway_token)
        print("Configuring gateway environment...")
        installer._configure_gateway_env(cname, uid, gid, home, gateway_token)

        # If openclaw is already onboarded (has device state in ~/.openclaw/),
        # just restart the gateway service — no need to re-run onboard.
        rc, _, _ = container_exec(
            cname,
            ["bash", "-c", f"test -d '{home}/.openclaw/devices' || test -d '{home}/.openclaw/identity'"],
            uid=uid, gid=gid,
            env={"HOME": home},
            check=False,
        )
        if rc == 0:
            print("openclaw already onboarded — restarting gateway service...")
            installer._restart_gateway(cname, uid, gid, home)
        else:
            print("Pairing gateway device (this takes ~10 seconds)...")
            installer._run_onboard(cname, uid, gid, home, gateway_token)
            installer._patch_gateway_token_in_json(cname, uid, gid, home, gateway_token)

        token = _read_gateway_token(token_dir)
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


# ── Lemonade recipes ──────────────────────────────────────────────────────────


@app.get("/api/containers/{name}/openclaw/model")
async def api_openclaw_model(name: str):
    """Return the primary model configured in openclaw.json, if present."""
    cname = _container_name(name)

    def _read():
        username, uid, gid, home = get_container_user(cname)
        raw = pull_file(cname, f"{home}/.openclaw/openclaw.json")
        config = json.loads(raw)
        primary = (
            config
            .get("agents", {})
            .get("defaults", {})
            .get("model", {})
            .get("primary", "")
        )
        if not primary:
            raise HTTPException(status_code=404, detail="No model configured")
        return {"model": primary}

    try:
        return await asyncio.to_thread(_read)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="openclaw not configured")


@app.get("/api/lemonade/recipes")
async def api_lemonade_recipes():
    """Fetch openclaw-recommended lemonade recipes from GitHub (cached 5 min)."""
    global _recipes_cache, _recipes_cache_ts
    now = _time.time()
    if _recipes_cache is not None and (now - _recipes_cache_ts) < _RECIPES_CACHE_TTL:
        return _recipes_cache

    def _fetch_recipes() -> list:
        def _get_json(url: str, timeout: int = 15) -> object:
            req = _urllib_request.Request(
                url,
                headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "ailab"},
            )
            with _urllib_request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())

        files = _get_json(_RECIPES_GITHUB_API)
        recipes = []
        for file_info in files:
            if not file_info["name"].endswith(".json"):
                continue
            try:
                recipe = _get_json(file_info["download_url"], timeout=10)
                recipe["_name"] = file_info["name"].removesuffix(".json")
                recipes.append(recipe)
            except Exception as exc:
                logger.warning("Skipping recipe %s: %s", file_info["name"], exc)
        recipes.sort(key=lambda r: r.get("size", 999))
        return recipes

    try:
        recipes = await asyncio.to_thread(_fetch_recipes)
        _recipes_cache = recipes
        _recipes_cache_ts = now
        return recipes
    except Exception as exc:
        logger.warning("Failed to fetch lemonade recipes: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to fetch recipes: {exc}")


@app.post("/api/containers/{name}/openclaw/import-recipe")
async def api_import_recipe(name: str, req: ImportRecipeRequest):
    """Import a lemonade recipe into lemonade-server and configure openclaw to use it."""
    cname = _container_name(name)
    recipe = req.recipe

    def task():
        model_name = recipe.get("model_name", "")
        recipe_label = recipe.get("_name", model_name)
        has_vision = "vision" in recipe.get("labels", [])
        ctx_size = recipe.get("recipe_options", {}).get("ctx_size", 32768)

        print(f"Importing recipe: {recipe_label}")

        port = _detect_lemonade_port()
        if port is None:
            print(
                "  Warning: lemonade-server not reachable — openclaw will be configured"
                " for this model; run lemonade pull to download it when lemonade starts"
            )
        else:
            print(f"  lemonade-server detected on port {port}")

            # Build the pull request: map recipe checkpoints format to lemonade's
            # pull API (POST /api/v1/pull), which registers the recipe in
            # user_models.json and downloads the model from HuggingFace.
            pull_data: dict = {"model_name": model_name}
            checkpoints = recipe.get("checkpoints")
            if checkpoints:
                pull_data["checkpoint"] = checkpoints.get("main", "")
                if "mmproj" in checkpoints:
                    pull_data["mmproj"] = checkpoints["mmproj"]
            elif "checkpoint" in recipe:
                pull_data["checkpoint"] = recipe["checkpoint"]

            for field in ("recipe", "recipe_options", "labels", "size"):
                if field in recipe:
                    pull_data[field] = recipe[field]

            print(f"  Registering {model_name} with lemonade-server and downloading...")
            size_gb = recipe.get("size")
            if size_gb:
                print(f"  Model size: ~{size_gb} GB — this may take a while")
            try:
                data = json.dumps(pull_data).encode()
                http_req = _urllib_request.Request(
                    f"http://127.0.0.1:{port}/api/v1/pull",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                # Use a long timeout — large model downloads can take many minutes.
                with _urllib_request.urlopen(http_req, timeout=7200) as resp:
                    result = json.loads(resp.read())
                    print(f"  Model registered: {result.get('model_name', model_name)}")
            except _urllib_error.HTTPError as e:
                body = e.read().decode(errors="replace")
                print(f"  Warning: lemonade pull returned {e.code}: {body} (non-fatal)")
            except Exception as e:
                print(f"  Warning: could not register model with lemonade: {e} (non-fatal)")

        lemonade_port = port or 13305
        username, uid, gid, home = get_container_user(cname)
        openclaw_json_path = f"{home}/.openclaw/openclaw.json"

        # Read current openclaw.json from inside the container, patch it on the
        # host, and write it back — avoids running a script inside the container.
        try:
            raw = pull_file(cname, openclaw_json_path)
            config = json.loads(raw)
        except Exception:
            config = {"gateway": {"mode": "local", "auth": {"mode": "token"}}}

        # Ensure models.mode and providers.lemonade are set correctly.
        models_section = config.setdefault("models", {"mode": "replace"})
        models_section.setdefault("mode", "replace")
        providers = models_section.setdefault("providers", {})
        lemon = providers.setdefault("lemonade", {})
        lemon["baseUrl"] = f"http://localhost:{lemonade_port}/api/v1"
        lemon["apiKey"] = "lemonade"
        lemon["api"] = "openai-completions"

        # Add model entry if not already listed.
        model_list = lemon.setdefault("models", [])
        existing_ids = {m["id"] for m in model_list if isinstance(m, dict) and "id" in m}
        if model_name not in existing_ids:
            model_list.insert(0, {
                "id": model_name,
                "name": model_name,
                "reasoning": False,
                "input": ["text", "image"] if has_vision else ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": ctx_size,
                "maxTokens": 8192,
            })

        # Set as primary model.
        (
            config
            .setdefault("agents", {})
            .setdefault("defaults", {})
            .setdefault("model", {})
        )["primary"] = f"lemonade/{model_name}"

        push_file(cname, openclaw_json_path, json.dumps(config, indent=2) + "\n")
        print(f"openclaw configured: primary model = lemonade/{model_name}")

    return _sse_stream(task)


# ── WebSocket: PTY shell ──────────────────────────────────────────────────────


@app.websocket("/api/ws/shell/{name}")
async def shell_ws(ws: WebSocket, name: str):
    await ws.accept()
    cname = _container_name(name)
    username, uid, gid, home = await asyncio.to_thread(_get_container_user, cname)

    try:
        welcome = await asyncio.to_thread(build_shell_welcome, name)
    except Exception as exc:
        logger.warning("build_shell_welcome failed for %s: %s", name, exc)
        welcome = "Welcome to your AI Lab container!"

    exec_data = {
        "command": ["/bin/bash", "--login"],
        "environment": {
            "HOME": home,
            "USER": username,
            "LOGNAME": username,
            "TERM": "xterm-256color",
            "XDG_RUNTIME_DIR": f"/run/user/{uid}",
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
            "SHELL_WELCOME": welcome,
        },
        "interactive": True,
        "wait-for-websocket": True,
        "cwd": home,
        "user": uid,
        "group": gid,
    }

    try:
        socket_path = _find_lxd_socket()
    except FileNotFoundError as exc:
        logger.error("LXD socket not found: %s", exc)
        await ws.send_text("\r\n[error: LXD socket not found]\r\n")
        return

    try:
        connector = aiohttp.UnixConnector(path=socket_path)
        async with aiohttp.ClientSession(connector=connector) as http:
            async with http.post(
                "http://localhost/1.0/instances/{}/exec".format(cname),
                params={"project": AILAB_PROJECT},
                json=exec_data,
            ) as resp:
                op = await resp.json()

            if op.get("status_code") not in (100, 200):
                err = op.get("error", "unknown error")
                logger.error("LXD exec failed for %s: %s  full response: %s", cname, err, op)
                await ws.send_text(f"\r\n[error: {err}]\r\n")
                return

            uuid = op["operation"].split("/")[-1]
            fds = op["metadata"]["metadata"]["fds"]
            data_secret = fds["0"]
            ctrl_secret = fds["control"]

            ws_url = "http://localhost/1.0/operations/{}/websocket".format(uuid)

            async with http.ws_connect(ws_url, params={"secret": data_secret}) as lxd_data, \
                       http.ws_connect(ws_url, params={"secret": ctrl_secret}) as lxd_ctrl:

                async def lxd_to_browser():
                    async for msg in lxd_data:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            await ws.send_bytes(msg.data)
                        elif msg.type == aiohttp.WSMsgType.TEXT:
                            await ws.send_text(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            break

                async def browser_to_lxd():
                    while True:
                        try:
                            msg = await ws.receive()
                        except WebSocketDisconnect:
                            break
                        if msg.get("type") == "websocket.disconnect":
                            break
                        raw_bytes = msg.get("bytes")
                        raw_text = msg.get("text")
                        if raw_bytes is not None:
                            await lxd_data.send_bytes(raw_bytes)
                        elif raw_text is not None:
                            try:
                                data = json.loads(raw_text)
                                if data.get("type") == "resize":
                                    cols = int(data["cols"])
                                    rows = int(data["rows"])
                                    await lxd_ctrl.send_json({
                                        "command": "window-resize",
                                        "args": {"width": str(cols), "height": str(rows)},
                                    })
                            except Exception:
                                await lxd_data.send_str(raw_text)

                t1 = asyncio.ensure_future(lxd_to_browser())
                t2 = asyncio.ensure_future(browser_to_lxd())
                try:
                    done, pending = await asyncio.wait(
                        [t1, t2], return_when=asyncio.FIRST_COMPLETED
                    )
                finally:
                    for task in [t1, t2]:
                        task.cancel()
                    await asyncio.gather(t1, t2, return_exceptions=True)
                    # Explicitly close LXD websockets so the Unix socket is freed
                    for lxd_ws in (lxd_data, lxd_ctrl):
                        try:
                            await lxd_ws.close()
                        except Exception:
                            pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("shell_ws error for %s: %s", name, exc, exc_info=True)
        try:
            await ws.send_text(f"\r\n[shell error: {exc}]\r\n")
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


# ── WebSocket: log tail ───────────────────────────────────────────────────────


@app.websocket("/api/ws/logs/{name}")
async def logs_ws(ws: WebSocket, name: str):
    await ws.accept()
    cname = _container_name(name)

    exec_data = {
        "command": ["journalctl", "-f", "-n", "50", "--no-pager"],
        "environment": {"TERM": "dumb"},
        "interactive": True,
        "wait-for-websocket": True,
    }

    try:
        socket_path = _find_lxd_socket()
    except FileNotFoundError as exc:
        await ws.send_text(f"[error: LXD socket not found: {exc}]")
        return

    try:
        connector = aiohttp.UnixConnector(path=socket_path)
        async with aiohttp.ClientSession(connector=connector) as http:
            async with http.post(
                "http://localhost/1.0/instances/{}/exec".format(cname),
                params={"project": AILAB_PROJECT},
                json=exec_data,
            ) as resp:
                op = await resp.json()

            if op.get("status_code") not in (100, 200):
                err = op.get("error", "unknown error")
                await ws.send_text(f"[error: {err}]")
                return

            uuid = op["operation"].split("/")[-1]
            fds = op["metadata"]["metadata"]["fds"]
            ctrl_secret = fds["control"]

            ws_url = "http://localhost/1.0/operations/{}/websocket".format(uuid)
            # Must connect to BOTH channels before LXD starts the exec
            async with http.ws_connect(ws_url, params={"secret": fds["0"]}) as lxd_ws, \
                       http.ws_connect(ws_url, params={"secret": ctrl_secret}) as _ctrl_ws:

                async def lxd_to_browser():
                    async for msg in lxd_ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            text = msg.data.decode(errors="replace")
                            for line in text.splitlines():
                                await ws.send_text(line)
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            break

                async def wait_for_disconnect():
                    try:
                        while True:
                            msg = await ws.receive()
                            if msg.get("type") == "websocket.disconnect":
                                break
                    except WebSocketDisconnect:
                        pass

                t1 = asyncio.ensure_future(lxd_to_browser())
                t2 = asyncio.ensure_future(wait_for_disconnect())
                try:
                    await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in [t1, t2]:
                        task.cancel()
                    await asyncio.gather(t1, t2, return_exceptions=True)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("logs_ws error for %s: %s", name, exc, exc_info=True)
        try:
            await ws.send_text(f"[log error: {exc}]")
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
