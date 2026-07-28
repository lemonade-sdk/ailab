"""Command-line interface for ailab."""

import argparse
import sys

from . import __version__
from .container import (
    add_port,
    create_container,
    delete_container,
    info_container,
    list_containers,
    list_ports,
    remove_port,
    run_container,
    stop_container,
    tail_logs,
)
from .doctor import DoctorError
from .installers import INSTALLERS, get_installer


# ── Subcommand handlers ────────────────────────────────────────────────────────

def cmd_new(args):
    extra = []
    for spec in args.port or []:
        try:
            host_s, container_s = spec.split(":")
            extra.append((int(host_s), int(container_s)))
        except ValueError:
            print(f"Invalid port spec '{spec}'. Use HOST_PORT:CONTAINER_PORT")
            sys.exit(1)

    # Validate any --install packages before doing any work
    installers = []
    for pkg in args.install or []:
        try:
            installers.append(get_installer(pkg))
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

    create_container(args.name, extra_outbound_ports=extra or None)

    if not installers:
        return

    for installer in installers:
        print()
        installer.install(args.name)

    # Collect onboard commands from packages that have them
    post_cmds = [i.onboard_cmd for i in installers if i.onboard_cmd]

    print()
    if post_cmds:
        print("Dropping into container for onboarding...")
    else:
        print("Dropping into container...")
    run_container(args.name, post_cmds=post_cmds or None)


def cmd_run(args):
    run_container(args.name)


def cmd_list(args):
    list_containers()


def cmd_stop(args):
    stop_container(args.name)


def cmd_delete(args):
    delete_container(args.name, force=args.force)


def cmd_install(args):
    try:
        installer = get_installer(args.package)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    installer.install(args.name)


def cmd_info(args):
    info_container(args.name)


def cmd_logs(args):
    tail_logs(args.name, follow=args.follow, lines=args.lines)


def cmd_doctor(args):
    from . import doctor

    checks = doctor.run_checks()
    print("AI Lab environment check:\n")
    print(doctor.format_checks(checks))
    print()
    if any(c.status == doctor.FAIL for c in checks):
        print("Some required checks failed — see the remedies above.")
        sys.exit(1)
    if any(c.status == doctor.WARN for c in checks):
        print("Required checks passed. Some optional services are unavailable (see above).")
    else:
        print("Everything looks good.")


def cmd_packages(args):
    from . import appstore

    catalog = appstore.get_catalog()
    snaps = appstore.get_snaps(catalog)

    print(f"{'PACKAGE':<16} {'PORTS':<16} DESCRIPTION")
    print("-" * 78)
    if snaps:
        for snap in sorted(snaps, key=lambda s: s["name"]):
            ports = ",".join(str(p) for p in appstore.get_ports(snap)) or "-"
            desc = snap.get("summary") or snap.get("title") or ""
            print(f"{snap['name']:<16} {ports:<16} {desc}")
        return

    # Catalog unreachable — fall back to the built-in table.
    for name, cls in sorted(INSTALLERS.items()):
        print(f"{name:<16} {'-':<16} {cls().description}")
    print()
    print("(could not reach the app catalog; showing the built-in list)")


def cmd_web(args):
    import os

    import uvicorn

    # Let the app (and the cloud tunnel client) know its own port for
    # dashboard-URL logging and tunnel auth injection.
    os.environ["AILAB_WEB_PORT"] = str(args.port)

    try:
        from .web.app import API_TOKEN, app
    except PermissionError:
        from .web.auth import token_file_path

        print(f"Error: permission denied writing the web API token at {token_file_path()}.")
        print()
        if os.environ.get("SNAP"):
            print("Under the snap, the web interface already runs as a background")
            print("service owned by root, so you don't need to (and can't) start it")
            print("as yourself. Get its dashboard URL with:")
            print()
            print("  sudo ailab dashboard")
            print()
            print("To run `ailab web` directly instead of using the service, use sudo.")
        else:
            print(f"Check that you own (or can write to) {token_file_path()}.")
        sys.exit(1)

    # Wildcard bind addresses aren't valid URLs to click on, so show a
    # browser-friendly host instead.  IPv6 literals need bracket-wrapping.
    if args.host in ("::", "0.0.0.0", ""):
        display_host = "localhost"
    elif ":" in args.host:
        display_host = f"[{args.host}]"
    else:
        display_host = args.host
    print(f"Starting ailab web interface at http://{display_host}:{args.port}")
    print(f"Dashboard (with access token): http://{display_host}:{args.port}/#token={API_TOKEN}")
    if args.reload:
        # uvicorn's reloader needs an import string, not an app object.
        uvicorn.run("ailab.web.app:app", host=args.host, port=args.port, reload=True)
    else:
        uvicorn.run(app, host=args.host, port=args.port)


def cmd_dashboard(args):
    from .web.auth import read_token, token_file_path

    token = read_token()
    if not token:
        print(f"No web API token found at {token_file_path()}.")
        print("Either the web daemon has not started yet, or you cannot read the file.")
        print("  Snap:     sudo ailab dashboard")
        print("  Non-snap: ailab web   (generates the token on first start)")
        sys.exit(1)
    url = f"http://127.0.0.1:{args.port}/#token={token}"
    print(url)


def cmd_complete(args):
    if args.kind == "packages":
        for name in sorted(INSTALLERS):
            print(name)
        return

    if args.kind == "commands":
        for name in ("new", "run", "stop", "list", "ls", "delete", "rm",
                     "install", "packages", "pkgs", "port", "web", "dashboard",
                     "doctor", "info", "logs"):
            print(name)
        return

    if args.kind == "port-actions":
        for name in ("add", "remove", "rm", "list", "ls"):
            print(name)
        return

    if args.kind == "containers":
        from .container import completion_container_names

        for name in completion_container_names():
            print(name)
        return


def cmd_port(args):
    if args.port_command == "add":
        try:
            host_port = int(args.host_port)
            container_port = int(args.container_port or args.host_port)
        except ValueError:
            print("Port numbers must be integers.")
            sys.exit(1)
        direction = "inbound" if args.inbound else "outbound"
        add_port(args.name, host_port, container_port, direction)

    elif args.port_command == "remove":
        try:
            host_port = int(args.port)
        except ValueError:
            print("Port number must be an integer.")
            sys.exit(1)
        direction = "inbound" if args.inbound else "outbound"
        remove_port(args.name, host_port, direction)

    elif args.port_command == "list":
        list_ports(args.name)


# ── Parser ────────────────────────────────────────────────────────────────────

class AilabArgumentParser(argparse.ArgumentParser):
    """ArgumentParser with a friendlier message for unknown subcommands."""

    def error(self, message):
        if message.startswith("argument COMMAND: invalid choice:"):
            bad = message.split("'")[1]
            self.print_usage(sys.stderr)
            sys.stderr.write(f"ailab: '{bad}' is not an ailab command. See 'ailab help'.\n")
            sys.exit(2)
        super().error(message)


def build_parser():
    available_pkgs = ", ".join(sorted(INSTALLERS))

    parser = AilabArgumentParser(
        prog="ailab",
        description=(
            "Manage LXD-based AI development sandboxes.\n\n"
            "Each container is wired to seamlessly use host AI services\n"
            "(lemonade-server, ollama) while keeping software isolated."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  ailab doctor                 Check your environment is ready
  ailab new mybox              Create a new sandbox named 'mybox'
  ailab install mybox openclaw Install openclaw (local-AI configured)
  ailab run mybox              Open a shell in 'mybox'
  ailab info mybox             Show status, ports, and installed tools
  ailab logs mybox -f          Follow the container's logs
  ailab stop mybox             Stop a running sandbox
  ailab list                   List all sandboxes
  ailab delete mybox           Delete a sandbox
  ailab packages               List installable packages
  ailab port add mybox 9000    Expose container port 9000 on host
""",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # ── new ────────────────────────────────────────────────────────────────────
    p_new = sub.add_parser(
        "new",
        help="Create a new sandbox container",
        description=(
            "Create a new LXD sandbox based on ubuntu:devel with:\n"
            "  • Your home directory mounted\n"
            "  • lemonade-server (port 8000 or 13305) and ollama (port 11434)\n"
            "    proxied so they appear local inside the container\n"
            "  • python3-venv, pip, nodejs, npm, bun, homebrew pre-installed"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_new.add_argument("name", help="Name for the sandbox")
    p_new.add_argument(
        "--port", "-p",
        metavar="HOST:CONTAINER",
        action="append",
        help="Extra port to forward from container to host (can repeat)",
    )
    p_new.add_argument(
        "--install", "-i",
        metavar="PACKAGE",
        action="append",
        help=(
            "Install a package after creation (can repeat). "
            "Packages with an onboard step run it automatically, "
            "then drops into an interactive shell. "
            f"Available: {available_pkgs}"
        ),
    )
    p_new.set_defaults(func=cmd_new)

    # ── run ────────────────────────────────────────────────────────────────────
    p_run = sub.add_parser("run", help="Open a shell inside a sandbox", aliases=["shell"])
    p_run.add_argument("name", help="Sandbox name")
    p_run.set_defaults(func=cmd_run)

    # ── stop ───────────────────────────────────────────────────────────────────
    p_stop = sub.add_parser("stop", help="Stop a running sandbox")
    p_stop.add_argument("name", help="Sandbox name")
    p_stop.set_defaults(func=cmd_stop)

    # ── list ───────────────────────────────────────────────────────────────────
    p_list = sub.add_parser("list", help="List all sandboxes", aliases=["ls"])
    p_list.set_defaults(func=cmd_list)

    # ── info ───────────────────────────────────────────────────────────────────
    p_info = sub.add_parser(
        "info",
        help="Show details about a sandbox",
        description=(
            "Show a sandbox's status, IP address, mapped user, config dir,\n"
            "forwarded ports, and installed packages (when running)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_info.add_argument("name", help="Sandbox name")
    p_info.set_defaults(func=cmd_info)

    # ── logs ───────────────────────────────────────────────────────────────────
    p_logs = sub.add_parser("logs", help="Show a sandbox's system logs")
    p_logs.add_argument("name", help="Sandbox name")
    p_logs.add_argument(
        "--follow", "-f", action="store_true",
        help="Follow the log output (Ctrl-C to stop)",
    )
    p_logs.add_argument(
        "--lines", "-n", type=int, default=50,
        help="Number of lines to show (default: 50)",
    )
    p_logs.set_defaults(func=cmd_logs)

    # ── doctor ─────────────────────────────────────────────────────────────────
    p_doctor = sub.add_parser(
        "doctor",
        help="Check that your environment is set up correctly",
        description=(
            "Check LXD is installed, initialised, and reachable, and report\n"
            "whether host AI services (lemonade-server, ollama) are available."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_doctor.set_defaults(func=cmd_doctor)

    # ── delete ─────────────────────────────────────────────────────────────────
    p_del = sub.add_parser("delete", help="Delete a sandbox", aliases=["rm"])
    p_del.add_argument("name", help="Sandbox name")
    p_del.add_argument(
        "--force", "-f",
        action="store_true",
        help="Skip confirmation prompt",
    )
    p_del.set_defaults(func=cmd_delete)

    # ── install ────────────────────────────────────────────────────────────────
    p_install = sub.add_parser(
        "install",
        help="Install a pre-configured package into a sandbox",
        description=(
            "Install a package into a sandbox with opinionated defaults.\n\n"
            "Packages are configured to prefer local AI providers\n"
            "(lemonade-server, ollama) over cloud services.\n\n"
            f"Available packages: {available_pkgs}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  ailab install mybox openclaw\n"
            "  ailab packages            (list all installable packages)\n"
        ),
    )
    p_install.add_argument("name", help="Sandbox name")
    p_install.add_argument(
        "package",
        help=f"Package to install ({available_pkgs})",
    )
    p_install.set_defaults(func=cmd_install)

    # ── packages ───────────────────────────────────────────────────────────────
    p_pkgs = sub.add_parser(
        "packages",
        help="List available installable packages",
        aliases=["pkgs"],
    )
    p_pkgs.set_defaults(func=cmd_packages)

    # ── help ───────────────────────────────────────────────────────────────────
    p_help = sub.add_parser("help", help="Show this help message")
    p_help.set_defaults(func=lambda args: parser.print_help())

    p_complete = sub.add_parser("_complete")
    p_complete.add_argument("kind", choices=["commands", "containers", "packages", "port-actions"])
    p_complete.set_defaults(func=cmd_complete)

    # ── web ────────────────────────────────────────────────────────────────────
    p_web = sub.add_parser("web", help="Start the ailab web management interface")
    p_web.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Host to bind to (default: 127.0.0.1 — local only). "
            "The API grants full container control to anyone who can reach it; "
            "only bind wider (e.g. 0.0.0.0) on a trusted network."
        ),
    )
    p_web.add_argument("--port", "-p", type=int, default=11500, help="Port to listen on (default: 11500)")
    p_web.add_argument("--reload", action="store_true", help="Enable auto-reload (development)")
    p_web.set_defaults(func=cmd_web)

    # ── dashboard ──────────────────────────────────────────────────────────────
    p_dash = sub.add_parser(
        "dashboard",
        help="Print the tokenized web dashboard URL",
        description=(
            "Print the local dashboard URL including the API access token.\n"
            "Under the snap the token file is root-owned: use sudo ailab dashboard."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_dash.add_argument("--port", "-p", type=int, default=11500, help="Web interface port (default: 11500)")
    p_dash.set_defaults(func=cmd_dashboard)

    # ── port ───────────────────────────────────────────────────────────────────
    p_port = sub.add_parser("port", help="Manage port proxies for a sandbox")
    port_sub = p_port.add_subparsers(dest="port_command", metavar="ACTION")
    port_sub.required = True

    # port add
    p_port_add = port_sub.add_parser(
        "add",
        help="Add a port proxy",
        description=(
            "Outbound (default): host browser → container service.\n"
            "  Useful for web UIs (openclaw, gradio, jupyter, etc.)\n\n"
            "Inbound (--inbound): container localhost → host service.\n"
            "  Useful for additional AI services running on the host."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_port_add.add_argument("name", help="Sandbox name")
    p_port_add.add_argument("host_port", help="Port on the host")
    p_port_add.add_argument(
        "container_port",
        nargs="?",
        help="Port inside the container (defaults to same as host_port)",
    )
    p_port_add.add_argument(
        "--inbound",
        action="store_true",
        help="Proxy container→host instead of host→container",
    )
    p_port_add.set_defaults(func=cmd_port, port_command="add")

    # port remove
    p_port_rm = port_sub.add_parser("remove", help="Remove a custom port proxy", aliases=["rm"])
    p_port_rm.add_argument("name", help="Sandbox name")
    p_port_rm.add_argument("port", help="Host port to remove")
    p_port_rm.add_argument("--inbound", action="store_true")
    p_port_rm.set_defaults(func=cmd_port, port_command="remove")

    # port list
    p_port_ls = port_sub.add_parser("list", help="List port proxies", aliases=["ls"])
    p_port_ls.add_argument("name", help="Sandbox name")
    p_port_ls.set_defaults(func=cmd_port, port_command="list")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except DoctorError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
