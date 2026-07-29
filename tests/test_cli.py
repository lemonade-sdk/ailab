"""Tests for CLI argument parsing (parser wiring, not command execution)."""

import pytest

from ailab.cli import build_parser


def test_new_with_install_and_ports():
    args = build_parser().parse_args(["new", "box", "-i", "openclaw", "-p", "5000:5000"])
    assert args.command == "new"
    assert args.name == "box"
    assert args.install == ["openclaw"]
    assert args.port == ["5000:5000"]


@pytest.mark.parametrize("argv,command", [
    (["run", "box"], "run"),
    (["shell", "box"], "shell"),
    (["stop", "box"], "stop"),
    (["list"], "list"),
    (["ls"], "ls"),
    (["info", "box"], "info"),
    (["logs", "box", "-f", "-n", "100"], "logs"),
    (["doctor"], "doctor"),
    (["dashboard"], "dashboard"),
    (["web"], "web"),
    (["packages"], "packages"),
])
def test_subcommands_parse(argv, command):
    args = build_parser().parse_args(argv)
    assert args.command == command
    assert callable(args.func)


def test_logs_flags():
    args = build_parser().parse_args(["logs", "box", "--follow", "--lines", "10"])
    assert args.follow is True
    assert args.lines == 10


def test_web_defaults_to_loopback():
    args = build_parser().parse_args(["web"])
    assert args.host == "127.0.0.1"
    assert args.port == 11500


def test_port_add_parses():
    args = build_parser().parse_args(["port", "add", "box", "9000", "--inbound"])
    assert args.port_command == "add"
    assert args.host_port == "9000"
    assert args.inbound is True


def test_missing_command_errors():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
