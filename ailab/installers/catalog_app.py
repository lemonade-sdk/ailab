"""Shared install logic for apps published in the nimbus-app-store catalog.

Mirrors the install flow nimbus-appliance/nimbus's backend uses
(services/control_plane.py's _do_nimbus_sideload): fetch the catalog entry,
`snap install --classic` it in the container, forward the ports it lists,
run its onboard command, run its post-install script, and start its
systemd user service. ailab execs directly into the container (no
in-container agent needed, unlike nimbus).
"""

from .. import appstore
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


class CatalogAppInstaller:
    """Base class for installers driven by the nimbus-app-store catalog.

    Subclasses set `app_id` (the catalog entry's `name`), plus `name`,
    `description`, and `onboard_cmd` (the CLI-level "drop into a shell and
    run this" command — unrelated to the catalog's own `onboard_cmd`, which
    runs automatically during install).
    """

    app_id: str = ""
    name: str = ""
    description: str = ""
    onboard_cmd: str | None = None

    def install(self, container_name: str):
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

        catalog = appstore.get_catalog()
        snap = appstore.get_snap(catalog, self.app_id)
        if snap is None:
            raise RuntimeError(
                f"'{self.app_id}' not found in the nimbus-app-store catalog "
                f"({appstore.CATALOG_URL})"
            )

        store_name = appstore.get_store_name(snap)
        channel = appstore.get_channel(snap)
        flags = appstore.get_install_flags(snap)

        install_cmd = ["snap", "install", store_name]
        if "--classic" in flags:
            install_cmd.append("--classic")
        if channel:
            install_cmd.append(f"--channel={channel}")
        print(f"Installing {store_name} (snap, channel={channel or 'stable'})...")
        container_exec(cname, install_cmd)

        ports = appstore.get_ports(snap)
        if ports:
            print(f"Adding port proxies ({', '.join(str(p) for p in ports)})...")
            self._add_port_proxies(cname, ports)

        env = {
            "HOME": home,
            "XDG_RUNTIME_DIR": f"/run/user/{uid}",
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
        }

        onboard = appstore.get_onboard_cmd(snap)
        if onboard:
            cmd, args = onboard
            print(f"Running onboard command: {cmd} {' '.join(args)}...")
            container_exec(cname, [cmd, *args], uid=uid, gid=gid, env=env, check=False)

        post_install_url = appstore.get_post_install_script_url(catalog, snap)
        if post_install_url:
            print("Running post-install script...")
            self._run_post_install_script(cname, uid, gid, home, post_install_url)

        service_name = appstore.get_service_name(snap)
        if service_name:
            self._service_action(cname, uid, gid, env, service_name, "enable --now")

        print()
        print(f"{store_name} installed in '{container_name}'.")
        print()
        print(f"  Start:  ailab run {container_name}")
        for port in ports:
            print(f"  Web UI: http://localhost:{port}")

    def run_post_install(self, container_name: str):
        """Re-fetch the catalog and re-run this app's post-install script.

        Generic re-configure/re-onboard action, driven entirely by the
        catalog entry — used e.g. to regenerate a config/token after install
        without repeating the (idempotent) snap install itself.
        """
        cname = _container_name(container_name)
        username, uid, gid, home = get_container_user(cname)
        catalog = appstore.get_catalog()
        snap = appstore.get_snap(catalog, self.app_id)
        if snap is None:
            raise RuntimeError(f"'{self.app_id}' not found in the nimbus-app-store catalog")
        url = appstore.get_post_install_script_url(catalog, snap)
        if url:
            self._run_post_install_script(cname, uid, gid, home, url)

    def restart_service(self, container_name: str):
        """Restart this app's systemd user service, per the catalog's service_name."""
        cname = _container_name(container_name)
        username, uid, gid, home = get_container_user(cname)
        catalog = appstore.get_catalog()
        snap = appstore.get_snap(catalog, self.app_id)
        service_name = appstore.get_service_name(snap) if snap else None
        if not service_name:
            return
        env = {
            "HOME": home,
            "XDG_RUNTIME_DIR": f"/run/user/{uid}",
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
        }
        self._service_action(cname, uid, gid, env, service_name, "restart")

    def _add_port_proxies(self, cname: str, ports: list[int]):
        for port in ports:
            device_name = f"proxy-out-{self.app_id}-{port}"
            if has_device(cname, device_name):
                continue
            ok = add_proxy_device(
                cname, device_name,
                f"tcp:127.0.0.1:{port}",
                f"tcp:127.0.0.1:{port}",
                bind="host",
            )
            if not ok:
                print(f"  Warning: port {port} already in use on host, skipping proxy device '{device_name}'")

    def _run_post_install_script(self, cname: str, uid: int, gid: int, home: str, url: str):
        try:
            script_content = appstore.fetch_text(url)
        except Exception as exc:
            print(f"  Warning: could not download post-install script (non-fatal): {exc}")
            return

        tmp_path = f"/tmp/ailab-post-install-{self.app_id}.sh"
        push_file(cname, tmp_path, script_content)
        container_exec(cname, ["chmod", "+x", tmp_path])

        exit_code, stdout, stderr = container_exec(
            cname,
            ["bash", tmp_path],
            uid=uid, gid=gid,
            env={
                "HOME": home,
                "XDG_RUNTIME_DIR": f"/run/user/{uid}",
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
                "PATH": "/snap/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            },
            check=False,
        )
        if exit_code != 0:
            print(f"  Warning: post-install script exited {exit_code} (non-fatal)")
            if stderr.strip():
                print(f"  {stderr.strip()}")
        container_exec(cname, ["rm", "-f", tmp_path], check=False)

    def _service_action(self, cname: str, uid: int, gid: int, env: dict, service_name: str, action: str):
        # "enable --now" during install is belt-and-suspenders — the snap's
        # own CLI launcher (run via the onboard command) already installs
        # and enables its unit. "restart" is used to pick up config changes.
        container_exec(
            cname,
            ["bash", "-c",
             "systemctl --user daemon-reload 2>/dev/null || true"
             f" && systemctl --user {action} {service_name} 2>/dev/null || true"],
            uid=uid, gid=gid,
            env=env,
            check=False,
        )
