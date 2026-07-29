"""Best-effort discovery of this host's own reachable IPv4 addresses.

Used to print dashboard links that actually work when `ailab web` is bound
to a wildcard address (0.0.0.0) instead of only showing 'localhost', which
would be wrong advice for anyone opening the link from another machine.

Deliberately dependency-free and snap-friendly: no netifaces/psutil, and no
shelling out to `ip addr` (which needs the network-observe interface ailab
doesn't request under strict confinement) — just ordinary socket calls the
existing `network` plug already covers.
"""

import socket


def local_ipv4_addresses() -> list[str]:
    """Return a best-effort, deduplicated list of this host's non-loopback
    IPv4 addresses. May miss secondary interfaces on multi-homed hosts;
    never raises."""
    addrs: set[str] = set()

    # The address the OS would use to reach the outside world. Reliable
    # even offline: UDP connect() only consults the routing table and
    # doesn't actually send anything.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            addrs.add(s.getsockname()[0])
    except OSError:
        pass

    # Whatever this host's own hostname resolves to — catches cases where
    # /etc/hosts or mDNS names an address the default-route trick above
    # wouldn't find.
    try:
        _, _, extra = socket.gethostbyname_ex(socket.gethostname())
        addrs.update(extra)
    except OSError:
        pass

    return sorted(a for a in addrs if not a.startswith("127."))


def bracket_if_ipv6(host: str) -> str:
    """Wrap a bare IPv6 literal for use in a URL, e.g. '::1' -> '[::1]'."""
    return f"[{host}]" if ":" in host else host


def dashboard_hosts(bind_host: str) -> list[str]:
    """Return the hostnames/IPs a dashboard link should be printed for,
    given the address `ailab web` is bound to.

    A wildcard bind (0.0.0.0, ::, or unset) expands to 'localhost' plus
    every address we could discover; a loopback bind stays 'localhost'
    only; any other specific address (a LAN IP passed to --host) is
    already known to be correct on its own.
    """
    if bind_host in ("0.0.0.0", "::", ""):
        return ["localhost", *local_ipv4_addresses()]
    if bind_host in ("127.0.0.1", "localhost", "::1"):
        return ["localhost"]
    return [bind_host]
