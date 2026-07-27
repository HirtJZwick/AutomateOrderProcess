"""Tests for excel_sync.py — reading the two Power Automate result workbooks."""
import datetime

import openpyxl

import excel_sync


def _write_oc_contacts(path, rows, header_row=1):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "OrderContacts"
    for _ in range(header_row - 1):
        ws.append([])
    ws.append(["Folder_Name", "Logistics_Coordinator", "Logistics_Coordinator_Email", "RSM", "RSM_Email"])
    for row in rows:
        ws.append(row)
    wb.save(path)


def _write_shipping_dates(path, rows, header_row=7):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ShippingDates"
    for _ in range(header_row - 1):
        ws.append([])
    ws.append(["Folder_Name", "Shipping_Date", "Reason", "Document"])
    for row in rows:
        ws.append(row)
    wb.save(path)


# ── lookup_oc_contacts ──────────────────────────────────────────────────────

def test_lookup_oc_contacts_returns_mapped_fields(tmp_path):
    path = tmp_path / "OC_Contacts.xlsx"
    _write_oc_contacts(path, [
        ["DO001 ACME", "Jane Doe", "jane@example.com", "John Smith", "john@example.com"],
    ])
    result = excel_sync.lookup_oc_contacts(str(tmp_path / "DO001 ACME"), path=str(path))
    assert result == {
        "logistics_coordinator": "Jane Doe",
        "logistics_coordinator_email": "jane@example.com",
        "rsm": "John Smith",
        "rsm_email": "john@example.com",
    }


def test_lookup_oc_contacts_matches_case_insensitively_and_ignores_separator(tmp_path):
    path = tmp_path / "OC_Contacts.xlsx"
    _write_oc_contacts(path, [
        ["do001 acme", "Jane Doe", "", "", ""],
    ])
    result = excel_sync.lookup_oc_contacts(str(tmp_path / "DO001 ACME") + "\\", path=str(path))
    assert result == {"logistics_coordinator": "Jane Doe"}


def test_lookup_oc_contacts_last_matching_row_wins(tmp_path):
    path = tmp_path / "OC_Contacts.xlsx"
    _write_oc_contacts(path, [
        ["DO001 ACME", "Old Name", "", "", ""],
        ["DO001 ACME", "New Name", "", "", ""],
    ])
    result = excel_sync.lookup_oc_contacts(str(tmp_path / "DO001 ACME"), path=str(path))
    assert result == {"logistics_coordinator": "New Name"}


def test_lookup_oc_contacts_missing_file_returns_empty_dict(tmp_path):
    result = excel_sync.lookup_oc_contacts(str(tmp_path / "DO001 ACME"), path=str(tmp_path / "missing.xlsx"))
    assert result == {}


def test_lookup_oc_contacts_no_match_returns_empty_dict(tmp_path):
    path = tmp_path / "OC_Contacts.xlsx"
    _write_oc_contacts(path, [["DO999 Other", "Jane Doe", "", "", ""]])
    result = excel_sync.lookup_oc_contacts(str(tmp_path / "DO001 ACME"), path=str(path))
    assert result == {}


# ── lookup_shipping_date ─────────────────────────────────────────────────────

def test_lookup_shipping_date_formats_datetime_cell(tmp_path):
    path = tmp_path / "Dossier_Shipping_Date.xlsx"
    _write_shipping_dates(path, [
        ["DO001 ACME", datetime.datetime(2026, 1, 29), "Found on the invoice", "Invoice.pdf"],
    ])
    result = excel_sync.lookup_shipping_date(str(tmp_path / "DO001 ACME"), path=str(path))
    assert result == {
        "shipping_date": "1/29/2026",
        "reasoning": "Found on the invoice",
        "source_document": "Invoice.pdf",
    }


def test_lookup_shipping_date_returns_empty_when_no_match(tmp_path):
    path = tmp_path / "Dossier_Shipping_Date.xlsx"
    _write_shipping_dates(path, [
        ["DO999 Other", datetime.datetime(2026, 1, 29), "", ""],
    ])
    result = excel_sync.lookup_shipping_date(str(tmp_path / "DO001 ACME"), path=str(path))
    assert result == {}


def test_lookup_shipping_date_returns_empty_when_date_cell_blank(tmp_path):
    path = tmp_path / "Dossier_Shipping_Date.xlsx"
    _write_shipping_dates(path, [
        ["DO001 ACME", None, "", ""],
    ])
    result = excel_sync.lookup_shipping_date(str(tmp_path / "DO001 ACME"), path=str(path))
    assert result == {}


def test_lookup_shipping_date_returns_reason_when_date_blank_but_reason_present(tmp_path):
    path = tmp_path / "Dossier_Shipping_Date.xlsx"
    _write_shipping_dates(path, [
        ["DO001 ACME", None, "No shipping documents uploaded yet", ""],
    ])
    result = excel_sync.lookup_shipping_date(str(tmp_path / "DO001 ACME"), path=str(path))
    assert result == {
        "shipping_date": None,
        "reasoning": "No shipping documents uploaded yet",
        "source_document": None,
    }


def test_lookup_shipping_date_missing_file_returns_empty_dict(tmp_path):
    result = excel_sync.lookup_shipping_date(str(tmp_path / "DO001 ACME"), path=str(tmp_path / "missing.xlsx"))
    assert result == {}


def test_lookup_latest_shipping_result_handles_generic_subfolder_name(tmp_path):
    path = tmp_path / "Dossier_Shipping_Date.xlsx"
    _write_shipping_dates(path, [
        ["DO999 Other", datetime.datetime(2026, 1, 29), "Older result", "Old.pdf"],
        [
            "Shipping Documents and Invoices",
            None,
            "The files only contain freight quotes, not a confirmed shipping date.",
            None,
        ],
    ])

    result = excel_sync.lookup_latest_shipping_result(path=str(path))

    assert result == {
        "shipping_date": None,
        "reasoning": "The files only contain freight quotes, not a confirmed shipping date.",
        "source_document": None,
    }


# ── _excel_root (per-installation workbook folder) ───────────────────────────

def test_excel_root_uses_configured_value_when_set(monkeypatch):
    monkeypatch.setattr(
        "webapp.backend.settings.load_config",
        lambda: {"excel_root": r"C:\Users\Eric\OneDrive - ZwickRoell GmbH & Co. KG\Documents\EricProject"},
    )
    assert excel_sync._excel_root() == (
        r"C:\Users\Eric\OneDrive - ZwickRoell GmbH & Co. KG\Documents\EricProject"
    )


def test_excel_root_falls_back_to_default_when_config_blank(monkeypatch):
    monkeypatch.setattr("webapp.backend.settings.load_config", lambda: {"excel_root": ""})
    assert excel_sync._excel_root() == excel_sync._DEFAULT_ERIC_PROJECT_ROOT
