"""Tests for power_automate.py — the two Power Automate flow triggers."""
import requests

import power_automate

_LOCAL_PATH = (
    r"C:\Users\Hirtj\OneDrive - ZwickRoell GmbH & Co. KG\Documents\EricProject\DO001 ACME"
)
_RELATIVE_PATH = "/Documents/EricProject/DO001 ACME"


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


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
    assert captured["json"] == {"folderPath": _RELATIVE_PATH}
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
    assert captured["json"] == {"dossier_no": "DO001", "folderPath": _RELATIVE_PATH}


def test_trigger_shipping_date_flow_returns_false_on_non_200(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda url, json, timeout: _FakeResponse(404))
    assert power_automate.trigger_shipping_date_flow("DO001", _LOCAL_PATH) is False


def test_trigger_shipping_date_flow_returns_false_on_request_exception(monkeypatch):
    def fake_post(url, json, timeout):
        raise requests.RequestException("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    assert power_automate.trigger_shipping_date_flow("DO001", _LOCAL_PATH) is False
