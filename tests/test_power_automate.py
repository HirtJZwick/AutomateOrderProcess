"""Tests for power_automate.py — the two Power Automate flow triggers."""
import pytest
import requests

import power_automate

_LOCAL_PATH = (
    r"C:\Users\Hirtj\OneDrive - ZwickRoell GmbH & Co. KG\Documents\EricProject\DO001 ACME"
)
_RELATIVE_PATH = "/Documents/EricProject/DO001 ACME"

# A synced SharePoint library, as recorded by the Windows sync-root registry:
# (MountPoint, FullRemotePath, WebUrl)
_SP_MOUNT = r"C:\Users\Hirtj\ZwickRoell GmbH & Co. KG\ZRG ZRNA - Website(Johannes)_Order_Folder"
_SP_REMOTE = (
    "https://zwickroell.sharepoint.com/sites/ZRGZRNA2/Freigegebene Dokumente"
    "/General/Dossier Room_/Website(Johannes)_Order_Folder"
)
_SP_SITE = "https://zwickroell.sharepoint.com/sites/ZRGZRNA2"
_SP_ORDER = _SP_MOUNT + r"\Order_Folders\DO737532 Henkel OPP450658"
_SP_EXPECTED = (
    "/Freigegebene Dokumente/General/Dossier Room_/Website(Johannes)_Order_Folder"
    "/Order_Folders/DO737532 Henkel OPP450658"
)


@pytest.fixture(autouse=True)
def _isolate_from_machine(monkeypatch):
    """Keep tests independent of the real sync roots / config on this machine."""
    monkeypatch.setattr(power_automate, "_sync_roots", lambda: [])
    monkeypatch.setattr("webapp.backend.settings.load_config", dict)


class _FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


# ── _onedrive_relative_path ──────────────────────────────────────────────────

def test_onedrive_relative_path_strips_local_prefix():
    assert power_automate._onedrive_relative_path(_LOCAL_PATH) == _RELATIVE_PATH


def test_onedrive_relative_path_is_case_insensitive_to_onedrive_segment():
    path = r"C:\Users\Milan\ONEDRIVE - ZwickRoell GmbH & Co. KG\Documents\EricProject\DO001 ACME"
    assert power_automate._onedrive_relative_path(path) == _RELATIVE_PATH


def test_onedrive_relative_path_falls_back_when_no_onedrive_segment(monkeypatch, capsys):
    path = r"C:\Users\Hirtj\SomeOtherFolder\DO001 ACME"
    result = power_automate._onedrive_relative_path(path)
    assert result == "C:/Users/Hirtj/SomeOtherFolder/DO001 ACME"
    assert "WARN" in capsys.readouterr().out


def test_trigger_oc_contacts_flow_posts_folder_path_and_returns_true_on_200(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse(200)

    monkeypatch.setattr(requests, "post", fake_post)
    result = power_automate.trigger_oc_contacts_flow(_LOCAL_PATH)

    assert result is True
    assert captured["url"] == power_automate.OC_CONTACTS_FLOW_URL
    assert captured["json"] == {"folderPath": _RELATIVE_PATH, "siteAddress": ""}
    assert captured["timeout"] == power_automate.FLOW_TIMEOUT_SECONDS


def test_trigger_oc_contacts_flow_returns_false_on_non_200(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda url, json, timeout: _FakeResponse(500))
    assert power_automate.trigger_oc_contacts_flow(_LOCAL_PATH) is False


def test_trigger_oc_contacts_flow_returns_false_on_request_exception(monkeypatch):
    def fake_post(url, json, timeout):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    assert power_automate.trigger_oc_contacts_flow(_LOCAL_PATH) is False


def test_trigger_shipping_date_flow_posts_dossier_and_folder_path(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse(200)

    monkeypatch.setattr(requests, "post", fake_post)
    result = power_automate.trigger_shipping_date_flow("DO001", _LOCAL_PATH)

    assert result is True
    assert captured["url"] == power_automate.SHIPPING_DATE_FLOW_URL
    assert captured["json"] == {
        "dossier_no": "DO001",
        "folderPath": _RELATIVE_PATH,
        "siteAddress": "",
    }


def test_trigger_shipping_date_flow_returns_false_on_non_200(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda url, json, timeout: _FakeResponse(404))
    assert power_automate.trigger_shipping_date_flow("DO001", _LOCAL_PATH) is False


def test_trigger_shipping_date_flow_returns_false_on_request_exception(monkeypatch):
    def fake_post(url, json, timeout):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    assert power_automate.trigger_shipping_date_flow("DO001", _LOCAL_PATH) is False


# ── config-driven flow URLs (per-installation flows) ─────────────────────────

def test_trigger_oc_contacts_flow_uses_configured_url_when_set(monkeypatch):
    monkeypatch.setattr(
        "webapp.backend.settings.load_config",
        lambda: {"oc_contacts_flow_url": "https://example.com/erics-oc-flow"},
    )
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        return _FakeResponse(200)

    monkeypatch.setattr(requests, "post", fake_post)
    power_automate.trigger_oc_contacts_flow(_LOCAL_PATH)
    assert captured["url"] == "https://example.com/erics-oc-flow"


def test_trigger_shipping_date_flow_falls_back_to_default_url_when_config_blank(monkeypatch):
    monkeypatch.setattr(
        "webapp.backend.settings.load_config",
        lambda: {"shipping_date_flow_url": ""},
    )
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        return _FakeResponse(200)

    monkeypatch.setattr(requests, "post", fake_post)
    power_automate.trigger_shipping_date_flow("DO001", _LOCAL_PATH)
    assert captured["url"] == power_automate.SHIPPING_DATE_FLOW_URL


# -- SharePoint synced library resolution ------------------------------------

def _use_sharepoint_sync_root(monkeypatch):
    monkeypatch.setattr(
        power_automate, "_sync_roots", lambda: [(_SP_MOUNT, _SP_REMOTE, _SP_SITE)]
    )


def test_flow_folder_path_resolves_synced_sharepoint_library(monkeypatch):
    """A synced SharePoint library has no "OneDrive - ..." segment; the sync
    registry must map it to its real site-relative path."""
    _use_sharepoint_sync_root(monkeypatch)
    assert power_automate._flow_folder_path(_SP_ORDER) == (_SP_EXPECTED, _SP_SITE)


def test_flow_folder_path_returns_sync_root_itself(monkeypatch):
    _use_sharepoint_sync_root(monkeypatch)
    path, site = power_automate._flow_folder_path(_SP_MOUNT)
    assert path == "/Freigegebene Dokumente/General/Dossier Room_/Website(Johannes)_Order_Folder"
    assert site == _SP_SITE


def test_flow_folder_path_ignores_unrelated_sync_root(monkeypatch):
    """A path outside every mount point falls back to the OneDrive strip."""
    _use_sharepoint_sync_root(monkeypatch)
    assert power_automate._flow_folder_path(_LOCAL_PATH) == (_RELATIVE_PATH, "")


def test_flow_folder_path_prefers_longest_matching_mount_point(monkeypatch):
    nested = _SP_MOUNT + r"\Order_Folders"
    monkeypatch.setattr(
        power_automate,
        "_sync_roots",
        lambda: [
            (_SP_MOUNT, _SP_REMOTE, _SP_SITE),
            (nested, _SP_REMOTE + "/Order_Folders", _SP_SITE),
        ],
    )
    path, _ = power_automate._flow_folder_path(_SP_ORDER)
    assert path == _SP_EXPECTED


def test_flow_folder_path_matches_case_insensitively(monkeypatch):
    _use_sharepoint_sync_root(monkeypatch)
    path, site = power_automate._flow_folder_path(_SP_ORDER.upper())
    assert path.startswith("/Freigegebene Dokumente/")
    assert site == _SP_SITE


def test_flow_folder_path_uses_config_mapping_first(monkeypatch):
    """An explicit config mapping wins over the registry lookup."""
    _use_sharepoint_sync_root(monkeypatch)
    monkeypatch.setattr(
        "webapp.backend.settings.load_config",
        lambda: {
            "root_folder": _SP_MOUNT,
            "sharepoint_site_url": "https://contoso.sharepoint.com/sites/Other/",
            "sharepoint_root_path": "Shared Documents/Orders",
        },
    )
    assert power_automate._flow_folder_path(_SP_ORDER) == (
        "/Shared Documents/Orders/Order_Folders/DO737532 Henkel OPP450658",
        "https://contoso.sharepoint.com/sites/Other",
    )


def test_flow_folder_path_config_mapping_ignored_for_path_outside_root(monkeypatch):
    monkeypatch.setattr(
        "webapp.backend.settings.load_config",
        lambda: {
            "root_folder": r"D:\SomewhereElse",
            "sharepoint_root_path": "/Shared Documents/Orders",
        },
    )
    assert power_automate._flow_folder_path(_LOCAL_PATH) == (_RELATIVE_PATH, "")


def test_trigger_oc_contacts_flow_sends_sharepoint_path_and_site(monkeypatch):
    _use_sharepoint_sync_root(monkeypatch)
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return _FakeResponse(200)

    monkeypatch.setattr(requests, "post", fake_post)
    assert power_automate.trigger_oc_contacts_flow(_SP_ORDER) is True
    assert captured["json"] == {"folderPath": _SP_EXPECTED, "siteAddress": _SP_SITE}


def test_sync_roots_reads_registry_without_raising(monkeypatch):
    """The real registry read must degrade gracefully, never explode."""
    monkeypatch.undo()  # drop the autouse isolation and hit the real registry
    roots = power_automate._sync_roots()
    assert isinstance(roots, list)
    assert all(len(entry) == 3 for entry in roots)


def test_relative_to_returns_empty_for_same_folder():
    assert power_automate._relative_to(_SP_MOUNT, _SP_MOUNT) == ""


def test_relative_to_returns_none_for_sibling_prefix():
    """A sibling folder sharing a name prefix must not be treated as inside."""
    assert power_automate._relative_to(_SP_MOUNT + "_Archive", _SP_MOUNT) is None


def test_relative_to_returns_none_for_unrelated_path():
    assert power_automate._relative_to(r"D:\Other\DO1", _SP_MOUNT) is None


def test_relative_to_returns_none_for_blank_root():
    assert power_automate._relative_to(_SP_MOUNT, "") is None


# ── flow response handling ──────────────────────────────────────────────────

_NO_RESPONSE_BODY = (
    '{"error":{"code":"NoResponse","message":"The server did not receive a response '
    'from an upstream server."}}'
)


def test_trigger_flow_treats_502_no_response_as_still_running(monkeypatch, capsys):
    """The flow outlived Power Automate's synchronous window but is running."""
    monkeypatch.setattr(requests, "post", lambda url, json, timeout: _FakeResponse(502, _NO_RESPONSE_BODY))

    assert power_automate.trigger_shipping_date_flow("DO001", _LOCAL_PATH) is True
    assert "still running" in capsys.readouterr().out


def test_trigger_flow_treats_202_as_still_running(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda url, json, timeout: _FakeResponse(202))
    assert power_automate.trigger_oc_contacts_flow(_LOCAL_PATH) is True


def test_trigger_flow_reports_a_real_502_as_failure(monkeypatch, capsys):
    """A 502 without NoResponse is a genuine upstream failure."""
    monkeypatch.setattr(
        requests, "post", lambda url, json, timeout: _FakeResponse(502, '{"error":{"code":"BadGateway"}}')
    )

    assert power_automate.trigger_shipping_date_flow("DO001", _LOCAL_PATH) is False
    assert "BadGateway" in capsys.readouterr().out


def test_trigger_flow_logs_status_and_body_on_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        requests, "post", lambda url, json, timeout: _FakeResponse(400, "File or folder not found")
    )

    assert power_automate.trigger_oc_contacts_flow(_LOCAL_PATH) is False
    out = capsys.readouterr().out
    assert "HTTP 400" in out
    assert "File or folder not found" in out
