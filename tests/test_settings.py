"""Tests for webapp/backend/settings.py — per-installation config.json."""
from webapp.backend import settings


def test_raw_config_defaults_flow_and_excel_keys_to_blank(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", str(tmp_path / "config.json"))
    cfg = settings._raw_config()
    assert cfg["oc_contacts_flow_url"] == ""
    assert cfg["shipping_date_flow_url"] == ""
    assert cfg["excel_root"] == ""


def test_save_config_persists_flow_and_excel_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONFIG_PATH", str(tmp_path / "config.json"))
    settings.save_config({
        "oc_contacts_flow_url": "https://example.com/oc",
        "shipping_date_flow_url": "https://example.com/ship",
        "excel_root": r"C:\Eric\EricProject",
    })
    cfg = settings._raw_config()
    assert cfg["oc_contacts_flow_url"] == "https://example.com/oc"
    assert cfg["shipping_date_flow_url"] == "https://example.com/ship"
    assert cfg["excel_root"] == r"C:\Eric\EricProject"
