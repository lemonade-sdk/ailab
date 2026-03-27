"""Command-line interface for ailab."""

import argparse
import sys

from . import __version__
from .container import (
    add_port,
    create_container,
    delete_container,
    list_containers,
    list_ports,
    remove_port,
    run_container,
    stop_container,
)
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


def cmd_packages(args):
    print(f"{'PACKAGE':<20} DESCRIPTION")
    print("-" * 70)
    for name, cls in sorted(INSTALLERS.items()):
        inst = cls()
        print(f"{name:<20} {inst.description}")


def cmd_complete(args):
    if args.kind == "packages":
        for name in sorted(INSTALLERS):
            print(name)
        return

    if args.kind == "commands":
        for name in ("new", "run", "stop", "list", "ls", "delete", "rm",
                     "install", "packages", "pkgs", "port"):
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

def build_parser():
    available_pkgs = ", ".join(sorted(INSTALLERS))

    parser = argparse.ArgumentParser(
        prog="ailab",
        description=(
            "Manage LXD-based AI development sandboxes.\n\n"
            "Each container is wired to seamlessly use host AI services\n"
            "(lemonade-server, ollama) while keeping software isolated."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  ailab new mybox              Create a new sandbox named 'mybox'
  ailab install mybox openclaw Install openclaw (local-AI configured)
  ailab run mybox              Open a shell in 'mybox'
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
            "  • lemonade-server (port 8000) and ollama (port 11434)\n"
            "    proxied so they appear local inside the container\n"
            "  • Common web UI ports forwarded to your host browser\n"
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
    p_run = sub.add_parser("run", help="Open a shell inside a sandbox")
    p_run.add_argument("name", help="Sandbox name")
    p_run.set_defaults(func=cmd_run)

    # ── stop ───────────────────────────────────────────────────────────────────
    p_stop = sub.add_parser("stop", help="Stop a running sandbox")
    p_stop.add_argument("name", help="Sandbox name")
    p_stop.set_defaults(func=cmd_stop)

    # ── list ───────────────────────────────────────────────────────────────────
    p_list = sub.add_parser("list", help="List all sandboxes", aliases=["ls"])
    p_list.set_defaults(func=cmd_list)

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

    p_complete = sub.add_parser("_complete", help=argparse.SUPPRESS)
    p_complete.add_argument("kind", choices=["commands", "containers", "packages", "port-actions"])
    p_complete.set_defaults(func=cmd_complete)

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
    args.func(args)


if __name__ == "__main__":
    main()
