"""Tests for the nimbus-app-store catalog accessors (pure parsing, no network)."""

from ailab import appstore

CATALOG = {
    "base_url": "https://example.com/catalog/",
    "snaps": [
        {
            "name": "openclaw",
            "summary": "Local-first AI assistant",
            "ports": [18789],
            "onboard_cmd": "openclaw.lemonade --auto",
            "post_install_script": "scripts/openclaw.sh",
            "service_name": "openclaw-gateway",
        },
        {
            "name": "nullclaw",
            "store_name": "nullclaw-snap",
            "channel": "edge",
            "install_flags": ["--classic", "--devmode"],
            "ports": [3002, 4173],
        },
    ],
}


def test_get_snaps_and_get_snap():
    snaps = appstore.get_snaps(CATALOG)
    assert [s["name"] for s in snaps] == ["openclaw", "nullclaw"]
    assert appstore.get_snap(CATALOG, "nullclaw")["store_name"] == "nullclaw-snap"
    assert appstore.get_snap(CATALOG, "missing") is None


def test_store_name_defaults_to_id():
    assert appstore.get_store_name(CATALOG["snaps"][0]) == "openclaw"
    assert appstore.get_store_name(CATALOG["snaps"][1]) == "nullclaw-snap"


def test_channel_and_flags():
    openclaw, nullclaw = CATALOG["snaps"]
    assert appstore.get_channel(openclaw) is None
    assert appstore.get_channel(nullclaw) == "edge"
    # Default install flags are --classic when unspecified.
    assert appstore.get_install_flags(openclaw) == ["--classic"]
    assert appstore.get_install_flags(nullclaw) == ["--classic", "--devmode"]


def test_ports_and_service():
    openclaw, nullclaw = CATALOG["snaps"]
    assert appstore.get_ports(openclaw) == [18789]
    assert appstore.get_ports(nullclaw) == [3002, 4173]
    assert appstore.get_service_name(openclaw) == "openclaw-gateway"
    assert appstore.get_service_name(nullclaw) is None


def test_onboard_cmd_split():
    openclaw, nullclaw = CATALOG["snaps"]
    assert appstore.get_onboard_cmd(openclaw) == ("openclaw.lemonade", ["--auto"])
    assert appstore.get_onboard_cmd(nullclaw) is None


def test_onboard_cmd_split_honors_quoting():
    snap = {"onboard_cmd": 'app.setup --path "/home/my user/config"'}
    assert appstore.get_onboard_cmd(snap) == ("app.setup", ["--path", "/home/my user/config"])


def test_onboard_cmd_split_falls_back_on_malformed_quoting():
    snap = {"onboard_cmd": "app.setup --path 'unterminated"}
    assert appstore.get_onboard_cmd(snap) == ("app.setup", ["--path", "'unterminated"])


def test_post_install_script_url_joins_base():
    url = appstore.get_post_install_script_url(CATALOG, CATALOG["snaps"][0])
    assert url == "https://example.com/catalog/scripts/openclaw.sh"
    assert appstore.get_post_install_script_url(CATALOG, CATALOG["snaps"][1]) is None
