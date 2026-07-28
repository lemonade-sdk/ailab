"""Tests for openclaw's dashboard-port selection.

The nimbus-app-store catalog's `ports` list isn't ordered by role, so code
that specifically needs openclaw's dashboard/gateway port must not just
assume ports[0] — a reordered or multi-port catalog entry would otherwise
silently point the token-authenticated dashboard link at the wrong port.
"""

from ailab.installers.openclaw import OPENCLAW_DASHBOARD_PORT, openclaw_dashboard_port


def test_prefers_the_known_dashboard_port_even_if_not_first():
    assert openclaw_dashboard_port([9999, OPENCLAW_DASHBOARD_PORT]) == OPENCLAW_DASHBOARD_PORT


def test_falls_back_to_first_port_when_dashboard_port_absent():
    assert openclaw_dashboard_port([9999, 8888]) == 9999


def test_none_when_no_ports():
    assert openclaw_dashboard_port([]) is None
