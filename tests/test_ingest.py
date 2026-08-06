import os

import pytest
import ingest
import extract_order_pdf
import storage


@pytest.fixture(autouse=True)
def _isolate_config_from_machine(monkeypatch):
    """Keep root-folder lookups off this machine's real config.json.

    `_configured_order_group()` and `_relocate_order_folder()` both read the
    live config; without this the tests would walk the real order tree.
    Tests that need a root install their own `load_config` stub.

    Flow-result polling is also collapsed to a single attempt so tests never
    sit through the real wait for a workbook row to sync down.
    """
    import webapp.backend.settings as settings
    import excel_sync

    monkeypatch.setattr(settings, "load_config", lambda: {})
    monkeypatch.setattr(excel_sync, "_flow_result_timeout", lambda: 0.0)


def _patch_workbook_freshness(monkeypatch):
    """Make the shipping workbook look modified after the flow was triggered.

    `ingest_folder` reads the mtime once before triggering; every later read
    must come back newer so the generic-row fallback is allowed.
    """
    calls = {"n": 0}

    def _mtime(path=None):
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else 1.0

    monkeypatch.setattr("excel_sync.workbook_mtime", _mtime)


def _patch_config_root(monkeypatch, root):
    """Point the config-backed root_folder lookups at `root`."""
    import webapp.backend.settings as settings

    monkeypatch.setattr(settings, "load_config", lambda: {"root_folder": str(root)})


# ── find_all_pdfs ──────────────────────────────────────────────────────────────

def test_find_all_pdfs_includes_oc_and_order_files(tmp_path):
    (tmp_path / "DO001 OC.pdf").write_bytes(b"")
    (tmp_path / "DO001 Order Confirmation.pdf").write_bytes(b"")
    hits = extract_order_pdf.find_all_pdfs(str(tmp_path))
    names = {p.split("\\")[-1].split("/")[-1] for p in hits}
    assert names == {"DO001 OC.pdf", "DO001 Order Confirmation.pdf"}


def test_find_all_pdfs_excludes_unrelated_files(tmp_path):
    (tmp_path / "Invoice 12345.pdf").write_bytes(b"")
    (tmp_path / "Packing List.pdf").write_bytes(b"")
    hits = extract_order_pdf.find_all_pdfs(str(tmp_path))
    assert hits == []


def test_find_all_pdfs_still_excludes_temp_and_backup(tmp_path):
    (tmp_path / "~$Order Confirmation.pdf").write_bytes(b"")
    (tmp_path / "Order Confirmation backup.pdf").write_bytes(b"")
    (tmp_path / "Order Confirmation.pdf").write_bytes(b"")
    hits = extract_order_pdf.find_all_pdfs(str(tmp_path))
    names = {p.split("\\")[-1].split("/")[-1] for p in hits}
    assert names == {"Order Confirmation.pdf"}


# ── find_shipping_pdfs ─────────────────────────────────────────────────────────

def test_find_shipping_pdfs_requires_shipping_subfolder(tmp_path):
    # No "Shipping Documents and Invoices" subfolder at all — even though an
    # invoice PDF sits directly in the order folder, it must not be found.
    (tmp_path / "Invoice 12345.pdf").write_bytes(b"")
    assert extract_order_pdf.find_shipping_pdfs(str(tmp_path)) == []


def test_find_shipping_pdfs_finds_invoice_shipping_and_quote_files(tmp_path):
    shipping_dir = tmp_path / "Shipping Documents and Invoices"
    shipping_dir.mkdir()
    (shipping_dir / "EMO TRANS - INVOICE - ATL2601D0002286.pdf").write_bytes(b"")
    (shipping_dir / "Shipping Confirmation.pdf").write_bytes(b"")
    (shipping_dir / "Freight Quote.pdf").write_bytes(b"")
    (shipping_dir / "Packing List.pdf").write_bytes(b"")
    hits = extract_order_pdf.find_shipping_pdfs(str(tmp_path))
    names = {p.split("\\")[-1].split("/")[-1] for p in hits}
    assert names == {
        "EMO TRANS - INVOICE - ATL2601D0002286.pdf",
        "Shipping Confirmation.pdf",
        "Freight Quote.pdf",
    }


def test_find_shipping_pdfs_skips_number_only_filenames(tmp_path):
    """Carrier invoices named after their number alone do not match."""
    shipping_dir = tmp_path / "Shipping Documents and Invoices"
    shipping_dir.mkdir()
    (shipping_dir / "1447745.pdf").write_bytes(b"")
    assert extract_order_pdf.find_shipping_pdfs(str(tmp_path)) == []


def test_has_shipping_subfolder_detects_the_folder(tmp_path):
    assert extract_order_pdf.has_shipping_subfolder(str(tmp_path)) is False
    (tmp_path / "Shipping Documents and Invoices").mkdir()
    assert extract_order_pdf.has_shipping_subfolder(str(tmp_path)) is True


def test_find_shipping_pdfs_ignores_invoices_outside_subfolder(tmp_path):
    # Invoice PDF sitting in a different subfolder must not be picked up.
    other_dir = tmp_path / "Other Docs"
    other_dir.mkdir()
    (other_dir / "Invoice 999.pdf").write_bytes(b"")
    assert extract_order_pdf.find_shipping_pdfs(str(tmp_path)) == []


# ── find_order_folders ────────────────────────────────────────────────────────

def test_find_order_folders_finds_checklist(tmp_path):
    sub = tmp_path / "DO001 ACME"
    sub.mkdir()
    (sub / "Checklist DO001.docx").write_bytes(b"")
    folders = ingest.find_order_folders(str(tmp_path))
    assert str(sub) in folders


def test_find_order_folders_ignores_temp_files(tmp_path):
    sub = tmp_path / "DO001 ACME"
    sub.mkdir()
    (sub / "~$Checklist DO001.docx").write_bytes(b"")  # Word temp lock file
    folders = ingest.find_order_folders(str(tmp_path))
    assert str(sub) not in folders


def test_find_order_folders_empty_root(tmp_path):
    assert ingest.find_order_folders(str(tmp_path)) == []


# ── categorize ────────────────────────────────────────────────────────────────

def test_categorize_checklist():
    assert ingest.categorize("Checklist DO001.docx") == "Checklist"


def test_categorize_order_confirmation():
    assert ingest.categorize("DO001 Order Confirmation.pdf") == "Order Confirmation"


def test_categorize_invoice():
    assert ingest.categorize("Invoice 12345.pdf") == "Invoice"


def test_categorize_shipping():
    assert ingest.categorize("Shipping Details.pdf") == "Packing / Shipping"


def test_categorize_unknown():
    assert ingest.categorize("some_random_file.pdf") == "Other"


# ── ingest_folder ─────────────────────────────────────────────────────────────

def test_ingest_folder_returns_none_without_checklist(tmp_path):
    folder = tmp_path / "DO001 ACME"
    folder.mkdir()
    result = ingest.ingest_folder(str(folder), db_path=str(tmp_path / "test.db"))
    assert result is None


def test_ingest_folder_stores_data(tmp_path, monkeypatch):
    folder = tmp_path / "DO001 ACME"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO001",
        "customer_name": "Test Corp",
        "order_date": "1/1/2026",
    })

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    assert result is not None
    assert result["dossier_no"] == "DO001"
    assert result["source_folder"] == str(folder)

    conn = storage.connect(db_path)
    storage.init_db(conn)
    order = storage.get_order(conn, "DO001")
    conn.close()
    assert order is not None
    assert order["customer_name"] == "Test Corp"


def test_ingest_folder_cancelled_flag(tmp_path, monkeypatch):
    folder = tmp_path / "DO001 Cancelled Order"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO001",
        "customer_name": "Test Corp",
        "order_date": "1/1/2026",
    })

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    assert result["cancelled"] == "1"

    # Also verify it was persisted to the DB
    conn = storage.connect(db_path)
    storage.init_db(conn)
    order = storage.get_order(conn, "DO001")
    conn.close()
    assert order["cancelled"] == "1"


def test_ingest_folder_no_cancelled_flag_for_normal_order(tmp_path, monkeypatch):
    folder = tmp_path / "DO002 Normal Order"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO002",
        "customer_name": "Normal Corp",
    })

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    assert result.get("cancelled") != "1"


def test_ingest_folder_stores_shipping_date_from_flow(tmp_path, monkeypatch):
    """When shipping PDFs are found, ingest_folder triggers the flow and stores
    the shipping_date looked up from the Excel workbook afterward."""
    folder = tmp_path / "DO011 Corp"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO011",
        "customer_name": "Corp",
    })
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr(
        "extract_order_pdf.find_shipping_pdfs",
        lambda f: [str(folder / "Shipping Documents and Invoices" / "Invoice.pdf")],
    )
    monkeypatch.setattr("power_automate.trigger_shipping_date_flow", lambda dossier_no, folder: True)
    monkeypatch.setattr(
        "excel_sync.lookup_shipping_date",
        lambda folder, path=None: {
            "shipping_date": "1/29/2026",
            "reasoning": "Found on the invoice",
            "source_document": "Invoice.pdf",
        },
    )

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    assert result["shipping_date"] == "1/29/2026"
    assert result["shipping_date_reason"] == "Found on the invoice"

    conn = storage.connect(db_path)
    storage.init_db(conn)
    order = storage.get_order(conn, "DO011")
    conn.close()
    assert order["shipping_date"] == "1/29/2026"
    assert order["shipping_date_reason"] == "Found on the invoice"


def test_ingest_folder_sets_warning_when_shipping_date_not_found(tmp_path, monkeypatch):
    """When the flow runs but no shipping date is found, ingest_folder returns
    a shipping_date_warning that states the reason from the workbook."""
    folder = tmp_path / "DO011b Corp"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO011B",
        "customer_name": "Corp",
    })
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr(
        "extract_order_pdf.find_shipping_pdfs",
        lambda f: [str(folder / "Shipping Documents and Invoices" / "Invoice.pdf")],
    )
    monkeypatch.setattr("power_automate.trigger_shipping_date_flow", lambda dossier_no, folder: True)
    monkeypatch.setattr(
        "excel_sync.lookup_shipping_date",
        lambda folder, path=None: {
            "shipping_date": None,
            "reasoning": "No shipping documents uploaded yet",
            "source_document": None,
        },
    )

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    assert result.get("shipping_date") is None
    assert result["shipping_date_reason"] == "No shipping documents uploaded yet"
    assert "No shipping documents uploaded yet" in result["shipping_date_warning"]


def test_ingest_folder_uses_latest_flow_row_when_folder_name_is_generic(tmp_path, monkeypatch):
    """HTTP 200 means the flow wrote its result, but the current flow sometimes
    stores the shipping subfolder name instead of the order folder name."""
    folder = tmp_path / "DO011f Corp"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO011F",
        "customer_name": "Corp",
    })
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr(
        "extract_order_pdf.find_shipping_pdfs",
        lambda f: [str(folder / "Shipping Documents and Invoices" / "Quote.pdf")],
    )
    monkeypatch.setattr("power_automate.trigger_shipping_date_flow", lambda dossier_no, folder: True)
    _patch_workbook_freshness(monkeypatch)
    monkeypatch.setattr("excel_sync.lookup_shipping_date", lambda folder, path=None: {})
    monkeypatch.setattr(
        "excel_sync.lookup_latest_shipping_result",
        lambda folder="", path=None: {
            "shipping_date": None,
            "reasoning": "The files only contain freight quotes, not a confirmed shipping date.",
            "source_document": None,
        },
    )

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    conn = storage.connect(db_path)
    storage.init_db(conn)
    order = storage.get_order(conn, "DO011F")
    conn.close()

    assert "flow failed" not in result["shipping_date_warning"]
    assert order["shipping_date_reason"] == (
        "The files only contain freight quotes, not a confirmed shipping date."
    )


def test_ingest_folder_sets_warning_when_shipping_date_flow_fails(tmp_path, monkeypatch):
    """When the flow call itself fails, ingest_folder still returns a warning,
    and still consults the workbook in case a prior run already wrote a row."""
    folder = tmp_path / "DO011c Corp"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO011C",
        "customer_name": "Corp",
    })
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr(
        "extract_order_pdf.find_shipping_pdfs",
        lambda f: [str(folder / "Shipping Documents and Invoices" / "Invoice.pdf")],
    )
    monkeypatch.setattr("power_automate.trigger_shipping_date_flow", lambda dossier_no, folder: False)
    monkeypatch.setattr("excel_sync.lookup_shipping_date", lambda folder, path=None: {})

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    assert result.get("shipping_date") is None
    assert "flow failed to run" in result["shipping_date_warning"]


def test_ingest_folder_uses_workbook_reason_even_when_flow_trigger_fails(tmp_path, monkeypatch):
    """A prior successful run may have already written a reason to the
    workbook; ingest_folder must still surface it even if THIS trigger call
    fails (e.g. a transient network error hitting the Flow endpoint)."""
    folder = tmp_path / "DO011e Corp"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO011E",
        "customer_name": "Corp",
    })
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr(
        "extract_order_pdf.find_shipping_pdfs",
        lambda f: [str(folder / "Shipping Documents and Invoices" / "Invoice.pdf")],
    )
    monkeypatch.setattr("power_automate.trigger_shipping_date_flow", lambda dossier_no, folder: False)
    monkeypatch.setattr(
        "excel_sync.lookup_shipping_date",
        lambda folder, path=None: {
            "shipping_date": None,
            "reasoning": "No shipping documents uploaded yet",
            "source_document": None,
        },
    )

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    assert result["shipping_date_reason"] == "No shipping documents uploaded yet"
    assert "No shipping documents uploaded yet" in result["shipping_date_warning"]
    assert "flow failed to run" in result["shipping_date_warning"]


def test_refresh_order_updates_stale_shipping_date_reason_once_date_is_found(tmp_path, monkeypatch):
    """A prior refresh recorded a 'not found yet' reason; the next refresh
    finds a real shipping date and must replace the stale reason, not keep it."""
    folder = tmp_path / "DO011d Corp"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO011D",
        "customer_name": "Corp",
    })
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr(
        "extract_order_pdf.find_shipping_pdfs",
        lambda f: [str(folder / "Shipping Documents and Invoices" / "Invoice.pdf")],
    )
    monkeypatch.setattr("power_automate.trigger_shipping_date_flow", lambda dossier_no, folder: True)

    db_path = str(tmp_path / "test.db")

    # First refresh: no date yet, only a "not found" reason.
    monkeypatch.setattr(
        "excel_sync.lookup_shipping_date",
        lambda folder, path=None: {
            "shipping_date": None,
            "reasoning": "No shipping documents uploaded yet",
            "source_document": None,
        },
    )
    ingest.ingest_folder(str(folder), db_path=db_path, merge="fill_empty")

    conn = storage.connect(db_path)
    storage.init_db(conn)
    order = storage.get_order(conn, "DO011D")
    conn.close()
    assert order["shipping_date_reason"] == "No shipping documents uploaded yet"

    # Second refresh: date now found with a fresh reason.
    monkeypatch.setattr(
        "excel_sync.lookup_shipping_date",
        lambda folder, path=None: {
            "shipping_date": "1/29/2026",
            "reasoning": "Found on the invoice",
            "source_document": "Invoice.pdf",
        },
    )
    ingest.ingest_folder(str(folder), db_path=db_path, merge="fill_empty")

    conn = storage.connect(db_path)
    order = storage.get_order(conn, "DO011D")
    conn.close()
    assert order["shipping_date"] == "1/29/2026"
    assert order["shipping_date_reason"] == "Found on the invoice"


def test_ingest_folder_skips_shipping_date_when_no_shipping_pdfs(tmp_path, monkeypatch):
    """No shipping PDFs found -> the shipping date flow is never triggered."""
    folder = tmp_path / "DO012 Corp"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO012",
        "customer_name": "Corp",
    })
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr("extract_order_pdf.find_shipping_pdfs", lambda f: [])

    def _fail_if_called(dossier_no, folder):
        raise AssertionError("trigger_shipping_date_flow should not be called with no shipping PDFs")

    monkeypatch.setattr("power_automate.trigger_shipping_date_flow", _fail_if_called)

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    assert result.get("shipping_date") is None


def test_ingest_folder_stores_contacts_from_flow(tmp_path, monkeypatch):
    """When local OC PDFs are found, ingest_folder triggers the OC contacts flow
    and merges the result looked up from the Excel workbook afterward."""
    folder = tmp_path / "DO013 Corp"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO013",
        "customer_name": "Corp",
    })
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [str(folder / "Order Confirmation.pdf")])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr("extract_order_pdf.find_shipping_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.extract", lambda p: {})
    monkeypatch.setattr("power_automate.trigger_oc_contacts_flow", lambda folder: True)
    monkeypatch.setattr(
        "excel_sync.lookup_oc_contacts",
        lambda folder, path=None: {"logistics_coordinator": "Jane Doe", "rsm": "John Smith"},
    )

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    assert result["logistics_coordinator"] == "Jane Doe"
    assert result["rsm"] == "John Smith"


def test_ingest_folder_skips_excel_lookup_when_flow_fails(tmp_path, monkeypatch):
    """If the OC contacts flow fails, the Excel lookup is never applied."""
    folder = tmp_path / "DO014 Corp"
    folder.mkdir()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {
        "dossier_no": "DO014",
        "customer_name": "Corp",
    })
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [str(folder / "Order Confirmation.pdf")])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr("extract_order_pdf.find_shipping_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.extract", lambda p: {})
    monkeypatch.setattr("power_automate.trigger_oc_contacts_flow", lambda folder: False)

    def _fail_if_called(folder, path=None):
        raise AssertionError("lookup_oc_contacts should not be called when the flow failed")

    monkeypatch.setattr("excel_sync.lookup_oc_contacts", _fail_if_called)

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    assert result.get("logistics_coordinator") is None


# ── ingest_folder merge modes ─────────────────────────────────────────────────

def _patch_extraction(monkeypatch, folder, extracted_data):
    """Helper: patch both checklist finders to return `extracted_data`."""
    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: dict(extracted_data))
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr("extract_order_pdf.find_shipping_pdfs", lambda f: [])


def test_ingest_folder_overwrite_mode_replaces_fields(tmp_path, monkeypatch):
    folder = tmp_path / "DO003 Corp"
    folder.mkdir()
    db_path = str(tmp_path / "test.db")

    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO003", "customer_name": "Original"})
    ingest.ingest_folder(str(folder), db_path=db_path)

    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO003", "customer_name": "Overwritten"})
    ingest.ingest_folder(str(folder), db_path=db_path, merge="overwrite")

    conn = storage.connect(db_path)
    storage.init_db(conn)
    assert storage.get_order(conn, "DO003")["customer_name"] == "Overwritten"
    conn.close()


def test_ingest_folder_fill_empty_does_not_overwrite(tmp_path, monkeypatch):
    folder = tmp_path / "DO004 Corp"
    folder.mkdir()
    db_path = str(tmp_path / "test.db")

    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO004", "customer_name": "Original"})
    ingest.ingest_folder(str(folder), db_path=db_path)

    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO004", "customer_name": "Should Not Win"})
    ingest.ingest_folder(str(folder), db_path=db_path, merge="fill_empty")

    conn = storage.connect(db_path)
    storage.init_db(conn)
    assert storage.get_order(conn, "DO004")["customer_name"] == "Original"
    conn.close()


def test_ingest_folder_fill_empty_fills_blank_fields(tmp_path, monkeypatch):
    folder = tmp_path / "DO005 Corp"
    folder.mkdir()
    db_path = str(tmp_path / "test.db")

    # First ingest: industry missing
    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO005", "customer_name": "Corp"})
    ingest.ingest_folder(str(folder), db_path=db_path)

    # Refresh: industry now extracted
    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO005", "industry": "Automotive"})
    ingest.ingest_folder(str(folder), db_path=db_path, merge="fill_empty")

    conn = storage.connect(db_path)
    storage.init_db(conn)
    order = storage.get_order(conn, "DO005")
    conn.close()
    assert order["industry"] == "Automotive"
    assert order["customer_name"] == "Corp"  # was populated, must not change


def test_ingest_folder_fill_empty_always_updates_documents(tmp_path, monkeypatch):
    folder = tmp_path / "DO006 Corp"
    folder.mkdir()
    db_path = str(tmp_path / "test.db")

    (folder / "Checklist.docx").write_bytes(b"")
    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO006", "customer_name": "Corp"})
    ingest.ingest_folder(str(folder), db_path=db_path)

    # Add a new document to the folder
    (folder / "Invoice_001.pdf").write_bytes(b"")
    ingest.ingest_folder(str(folder), db_path=db_path, merge="fill_empty")

    conn = storage.connect(db_path)
    storage.init_db(conn)
    docs = storage.get_documents(conn, "DO006")
    conn.close()
    assert any(d["file_name"] == "Invoice_001.pdf" for d in docs)


# ── refresh_order ─────────────────────────────────────────────────────────────

def test_refresh_order_fills_empty_fields(tmp_path, monkeypatch):
    folder = tmp_path / "DO007 Corp"
    folder.mkdir()
    db_path = str(tmp_path / "test.db")

    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO007", "customer_name": "Corp"})
    ingest.ingest_folder(str(folder), db_path=db_path)

    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO007", "industry": "Medical"})
    result = ingest.refresh_order("DO007", db_path=db_path)

    assert result["order"]["industry"] == "Medical"
    assert result["order"]["customer_name"] == "Corp"
    assert "documents" in result


def test_refresh_order_never_overwrites_populated(tmp_path, monkeypatch):
    folder = tmp_path / "DO008 Corp"
    folder.mkdir()
    db_path = str(tmp_path / "test.db")

    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO008", "customer_name": "Original"})
    ingest.ingest_folder(str(folder), db_path=db_path)

    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO008", "customer_name": "Intruder"})
    result = ingest.refresh_order("DO008", db_path=db_path)

    assert result["order"]["customer_name"] == "Original"


def test_refresh_order_adds_new_documents(tmp_path, monkeypatch):
    folder = tmp_path / "DO009 Corp"
    folder.mkdir()
    db_path = str(tmp_path / "test.db")

    (folder / "Checklist.docx").write_bytes(b"")
    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO009", "customer_name": "Corp"})
    ingest.ingest_folder(str(folder), db_path=db_path)

    # Anita drops an invoice into the folder
    (folder / "Invoice_final.pdf").write_bytes(b"")
    result = ingest.refresh_order("DO009", db_path=db_path)

    assert any(d["file_name"] == "Invoice_final.pdf" for d in result["documents"])


def test_refresh_order_raises_for_missing_order(tmp_path):
    db_path = str(tmp_path / "test.db")
    with pytest.raises(ValueError, match="not found"):
        ingest.refresh_order("DOESNOTEXIST", db_path=db_path)


def test_refresh_order_raises_for_missing_folder(tmp_path, monkeypatch):
    folder = tmp_path / "DO010 Corp"
    folder.mkdir()
    db_path = str(tmp_path / "test.db")

    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO010", "customer_name": "Corp"})
    ingest.ingest_folder(str(folder), db_path=db_path)

    # Remove the folder from disk
    import shutil
    shutil.rmtree(str(folder))

    with pytest.raises(ValueError, match="source_folder"):
        ingest.refresh_order("DO010", db_path=db_path)


def test_refresh_order_relocates_folder_after_root_change(tmp_path, monkeypatch):
    """The synced root moved: refresh finds the folder again and rebinds it."""
    old_root = tmp_path / "OldRoot"
    old_folder = old_root / "Order_Folders" / "DO011 Henkel"
    old_folder.mkdir(parents=True)
    (old_folder / "Checklist DO011.docx").write_bytes(b"")
    db_path = str(tmp_path / "test.db")

    _patch_config_root(monkeypatch, old_root)
    _patch_extraction(monkeypatch, old_folder, {"dossier_no": "DO011", "customer_name": "Henkel"})
    ingest.scan_new(str(old_root), db_path=db_path)

    # The library re-syncs under a brand new root; the old one disappears.
    new_root = tmp_path / "NewRoot"
    new_folder = new_root / "Order_Folders" / "DO011 Henkel"
    new_folder.mkdir(parents=True)
    (new_folder / "Checklist DO011.docx").write_bytes(b"")
    import shutil
    shutil.rmtree(str(old_root))

    _patch_config_root(monkeypatch, new_root)
    _patch_extraction(monkeypatch, new_folder, {"dossier_no": "DO011", "industry": "Chemicals"})
    result = ingest.refresh_order("DO011", db_path=db_path)

    assert result["order"]["source_folder"] == "Order_Folders/DO011 Henkel"
    assert result["order"]["order_group"] == "Order_Folders"
    assert result["order"]["industry"] == "Chemicals"


def test_refresh_order_relocation_survives_group_change(tmp_path, monkeypatch):
    """A folder moved to the other category is found and re-tagged."""
    root = tmp_path / "Root"
    classic = root / "Order_Folders" / "DO012 ACME"
    classic.mkdir(parents=True)
    (classic / "Checklist DO012.docx").write_bytes(b"")
    db_path = str(tmp_path / "test.db")

    _patch_config_root(monkeypatch, root)
    _patch_extraction(monkeypatch, classic, {"dossier_no": "DO012", "customer_name": "ACME"})
    ingest.scan_new(str(root), db_path=db_path)

    machine = root / "New_Machines_Order_Folder" / "DO012 ACME"
    machine.parent.mkdir(parents=True)
    import shutil
    shutil.move(str(classic), str(machine))

    _patch_extraction(monkeypatch, machine, {"dossier_no": "DO012"})
    result = ingest.refresh_order("DO012", db_path=db_path)

    assert result["order"]["source_folder"] == "New_Machines_Order_Folder/DO012 ACME"
    assert result["order"]["order_group"] == "New_Machines_Order_Folder"


def test_refresh_order_error_names_the_scan_folder_remedy(tmp_path, monkeypatch):
    """When relocation fails the message tells the user what to do."""
    root = tmp_path / "Root"
    folder = root / "Order_Folders" / "DO013 Gone"
    folder.mkdir(parents=True)
    (folder / "Checklist DO013.docx").write_bytes(b"")
    db_path = str(tmp_path / "test.db")

    _patch_config_root(monkeypatch, root)
    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO013", "customer_name": "Gone"})
    ingest.scan_new(str(root), db_path=db_path)

    import shutil
    shutil.rmtree(str(folder))

    with pytest.raises(ValueError, match="Scan new orders"):
        ingest.refresh_order("DO013", db_path=db_path)


def test_relocate_order_folder_returns_none_without_configured_root(tmp_path):
    assert ingest._relocate_order_folder(str(tmp_path / "DO999 Nobody")) is None


def test_relocate_order_folder_matches_by_folder_name(tmp_path, monkeypatch):
    root = tmp_path / "Root"
    folder = root / "Order_Folders" / "DO014 Indomo"
    folder.mkdir(parents=True)
    (folder / "Checklist DO014.docx").write_bytes(b"")

    _patch_config_root(monkeypatch, root)
    found = ingest._relocate_order_folder(r"D:\Some\Old\Root\Order_Folders\DO014 Indomo")

    assert found == (str(folder), "Order_Folders")


# ── scan_new: folder-name identity across different OneDrive roots ──────────

def test_scan_new_skips_known_order_with_different_root_path(tmp_path, monkeypatch):
    """Same order folder name under a different OneDrive-style root must be
    recognized as already known, not re-ingested."""
    # Simulate Milan's OneDrive root, already ingested.
    milan_root = tmp_path / "MilanE" / "OneDrive" / "EricProject"
    milan_folder = milan_root / "Classic Orders" / "DO860728 Acom Labs OPP450766"
    milan_folder.mkdir(parents=True)
    (milan_folder / "Checklist DO860728.docx").write_bytes(b"")

    db_path = str(tmp_path / "test.db")
    _patch_extraction(monkeypatch, milan_folder, {"dossier_no": "DO860728", "customer_name": "Acom Labs"})
    ingest.ingest_folder(str(milan_folder), db_path=db_path)

    # Now simulate Eric's OneDrive root with the SAME final folder name.
    eric_root = tmp_path / "Hirtj" / "OneDrive" / "EricProject"
    eric_folder = eric_root / "Classic Orders" / "DO860728 Acom Labs OPP450766"
    eric_folder.mkdir(parents=True)
    (eric_folder / "Checklist DO860728.docx").write_bytes(b"")

    def _fail_if_called(folder, **kwargs):
        raise AssertionError("ingest_folder should not be called for a known folder name")

    monkeypatch.setattr(ingest, "ingest_folder", _fail_if_called)

    result = ingest.scan_new(str(eric_root), db_path=db_path)

    assert result["folders_found"] == 1
    assert result["new_folders_found"] == 0
    assert result["ingested_count"] == 0


def test_scan_new_rebinds_source_folder_to_current_path(tmp_path, monkeypatch):
    """When the matching order is found at a different absolute path, the
    stored source_folder must be updated to the currently scanned path."""
    milan_root = tmp_path / "MilanE" / "OneDrive" / "EricProject"
    milan_folder = milan_root / "Classic Orders" / "DO860728 Acom Labs OPP450766"
    milan_folder.mkdir(parents=True)
    (milan_folder / "Checklist DO860728.docx").write_bytes(b"")

    db_path = str(tmp_path / "test.db")
    _patch_extraction(monkeypatch, milan_folder, {"dossier_no": "DO860728", "customer_name": "Acom Labs"})
    ingest.ingest_folder(str(milan_folder), db_path=db_path)

    eric_root = tmp_path / "Hirtj" / "OneDrive" / "EricProject"
    eric_folder = eric_root / "Classic Orders" / "DO860728 Acom Labs OPP450766"
    eric_folder.mkdir(parents=True)
    (eric_folder / "Checklist DO860728.docx").write_bytes(b"")

    ingest.scan_new(str(eric_root), db_path=db_path)

    conn = storage.connect(db_path)
    storage.init_db(conn)
    order = storage.get_order(conn, "DO860728")
    conn.close()
    assert order["source_folder"] == str(eric_folder)


def test_scan_new_rebind_lets_refresh_work_from_new_path(tmp_path, monkeypatch):
    """After rebinding, refresh_order must succeed using the new local path."""
    milan_root = tmp_path / "MilanE" / "OneDrive" / "EricProject"
    milan_folder = milan_root / "Classic Orders" / "DO860728 Acom Labs OPP450766"
    milan_folder.mkdir(parents=True)
    (milan_folder / "Checklist DO860728.docx").write_bytes(b"")

    db_path = str(tmp_path / "test.db")
    _patch_extraction(monkeypatch, milan_folder, {"dossier_no": "DO860728", "customer_name": "Acom Labs"})
    ingest.ingest_folder(str(milan_folder), db_path=db_path)

    eric_root = tmp_path / "Hirtj" / "OneDrive" / "EricProject"
    eric_folder = eric_root / "Classic Orders" / "DO860728 Acom Labs OPP450766"
    eric_folder.mkdir(parents=True)
    (eric_folder / "Checklist DO860728.docx").write_bytes(b"")

    ingest.scan_new(str(eric_root), db_path=db_path)

    # Milan's original folder no longer exists on this machine; refresh must
    # use the rebound Eric folder, not raise for a missing source_folder.
    import shutil
    shutil.rmtree(str(milan_root))

    _patch_extraction(monkeypatch, eric_folder, {"dossier_no": "DO860728", "industry": "Automotive"})
    result = ingest.refresh_order("DO860728", db_path=db_path)
    assert result["order"]["industry"] == "Automotive"


def test_scan_new_still_ingests_genuinely_new_folder_name(tmp_path, monkeypatch):
    root = tmp_path / "EricProject"
    folder = root / "Classic Orders" / "DO999999 New Customer"
    folder.mkdir(parents=True)
    (folder / "Checklist DO999999.docx").write_bytes(b"")

    db_path = str(tmp_path / "test.db")
    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO999999", "customer_name": "New Customer"})

    result = ingest.scan_new(str(root), db_path=db_path)

    assert result["new_folders_found"] == 1
    assert result["ingested"] == ["DO999999"]


def test_scan_new_folder_name_matching_is_case_insensitive(tmp_path, monkeypatch):
    milan_root = tmp_path / "MilanE" / "EricProject"
    milan_folder = milan_root / "Classic Orders" / "do860728 acom labs opp450766"
    milan_folder.mkdir(parents=True)
    (milan_folder / "Checklist DO860728.docx").write_bytes(b"")

    db_path = str(tmp_path / "test.db")
    _patch_extraction(monkeypatch, milan_folder, {"dossier_no": "DO860728", "customer_name": "Acom Labs"})
    ingest.ingest_folder(str(milan_folder), db_path=db_path)

    eric_root = tmp_path / "Hirtj" / "EricProject"
    eric_folder = eric_root / "Classic Orders" / "DO860728 ACOM LABS OPP450766"
    eric_folder.mkdir(parents=True)
    (eric_folder / "Checklist DO860728.docx").write_bytes(b"")

    result = ingest.scan_new(str(eric_root), db_path=db_path)

    assert result["folders_found"] == 1
    assert result["new_folders_found"] == 0
    assert result["ingested_count"] == 0


def test_folder_identity_ignores_trailing_separator():
    assert ingest._folder_identity(r"C:\root\DO001 ACME" + "\\") == ingest._folder_identity(r"C:\root\DO001 ACME")


# ── two order subfolders under the root (classic + machine orders) ───────────

def _make_two_group_root(tmp_path):
    """Root holding a classic and a machine order subfolder, one order each."""
    root = tmp_path / "EricProject"
    classic = root / "Classic Orders" / "DO001 ACME"
    machine = root / "Machine Orders" / "DO002 Globex"
    classic.mkdir(parents=True)
    machine.mkdir(parents=True)
    (classic / "Checklist DO001.docx").write_bytes(b"")
    (machine / "Checklist DO002.docx").write_bytes(b"")
    return root, classic, machine


def test_list_order_groups_returns_immediate_subfolders_sorted(tmp_path):
    root, _, _ = _make_two_group_root(tmp_path)
    assert ingest.list_order_groups(str(root)) == ["Classic Orders", "Machine Orders"]


def test_list_order_groups_skips_files_and_hidden_folders(tmp_path):
    root = tmp_path / "EricProject"
    (root / "Machine Orders").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "~$lock").mkdir()
    (root / "notes.txt").write_text("x", encoding="utf-8")
    assert ingest.list_order_groups(str(root)) == ["Machine Orders"]


def test_list_order_groups_missing_root_returns_empty(tmp_path):
    assert ingest.list_order_groups(str(tmp_path / "nope")) == []


def test_find_order_folders_by_group_covers_both_subfolders(tmp_path):
    root, classic, machine = _make_two_group_root(tmp_path)
    pairs = ingest.find_order_folders_by_group(str(root))
    assert pairs == [
        ("Classic Orders", str(classic)),
        ("Machine Orders", str(machine)),
    ]


def test_find_order_folders_by_group_ignores_order_folder_in_root(tmp_path):
    """An order folder sitting directly in the root is not an order group."""
    root, classic, _ = _make_two_group_root(tmp_path)
    loose = root / "DO900 Loose Order"
    loose.mkdir()
    (loose / "Checklist DO900.docx").write_bytes(b"")

    folders = [folder for _, folder in ingest.find_order_folders_by_group(str(root))]
    assert str(loose) not in folders
    assert str(classic) in folders


def test_find_order_folders_by_group_handles_nested_order_folders(tmp_path):
    """A deeper structure inside a subfolder still reports the top subfolder."""
    root = tmp_path / "EricProject"
    nested = root / "Machine Orders" / "2026" / "DO003 Initech"
    nested.mkdir(parents=True)
    (nested / "Checklist DO003.docx").write_bytes(b"")
    assert ingest.find_order_folders_by_group(str(root)) == [("Machine Orders", str(nested))]


def test_scan_root_ingests_orders_from_both_subfolders(tmp_path, monkeypatch):
    root, classic, machine = _make_two_group_root(tmp_path)
    db_path = str(tmp_path / "test.db")

    _patch_extraction(monkeypatch, classic, {})
    monkeypatch.setattr(
        "extract_checklist.extract",
        lambda p: {"dossier_no": "DO001"} if "Classic" in str(p) else {"dossier_no": "DO002"},
    )
    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: os.path.join(f, "Checklist.docx"))

    result = ingest.scan_root(str(root), db_path=db_path)

    assert result["folders_found"] == 2
    assert sorted(result["ingested"]) == ["DO001", "DO002"]
    assert result["groups"] == ["Classic Orders", "Machine Orders"]


def test_scan_root_records_order_group_per_order(tmp_path, monkeypatch):
    root, classic, machine = _make_two_group_root(tmp_path)
    db_path = str(tmp_path / "test.db")

    _patch_extraction(monkeypatch, classic, {})
    monkeypatch.setattr(
        "extract_checklist.extract",
        lambda p: {"dossier_no": "DO001"} if "Classic" in str(p) else {"dossier_no": "DO002"},
    )
    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: os.path.join(f, "Checklist.docx"))

    ingest.scan_root(str(root), db_path=db_path)

    conn = storage.connect(db_path)
    storage.init_db(conn)
    assert storage.get_order(conn, "DO001")["order_group"] == "Classic Orders"
    assert storage.get_order(conn, "DO002")["order_group"] == "Machine Orders"
    conn.close()


def test_scan_new_ingests_new_order_from_machine_subfolder(tmp_path, monkeypatch):
    """A new order added to the machine subfolder is picked up while the
    already-known classic order is skipped."""
    root, classic, machine = _make_two_group_root(tmp_path)
    db_path = str(tmp_path / "test.db")

    _patch_extraction(monkeypatch, classic, {"dossier_no": "DO001", "customer_name": "ACME"})
    ingest.ingest_folder(str(classic), db_path=db_path, order_group="Classic Orders")

    _patch_extraction(monkeypatch, machine, {"dossier_no": "DO002", "customer_name": "Globex"})
    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: os.path.join(f, "Checklist.docx"))

    result = ingest.scan_new(str(root), db_path=db_path)

    assert result["folders_found"] == 2
    assert result["new_folders_found"] == 1
    assert result["ingested"] == ["DO002"]

    conn = storage.connect(db_path)
    storage.init_db(conn)
    assert storage.get_order(conn, "DO002")["order_group"] == "Machine Orders"
    conn.close()


def test_scan_new_backfills_order_group_for_previously_ingested_order(tmp_path, monkeypatch):
    """Orders ingested before the order_group column existed get tagged on the
    next scan without being re-ingested."""
    root = tmp_path / "EricProject"
    classic = root / "Classic Orders" / "DO001 ACME"
    classic.mkdir(parents=True)
    (classic / "Checklist DO001.docx").write_bytes(b"")
    db_path = str(tmp_path / "test.db")

    _patch_extraction(monkeypatch, classic, {"dossier_no": "DO001", "customer_name": "ACME"})
    ingest.ingest_folder(str(classic), db_path=db_path)  # no order_group

    conn = storage.connect(db_path)
    storage.init_db(conn)
    assert storage.get_order(conn, "DO001")["order_group"] in (None, "")
    conn.close()

    monkeypatch.setattr(
        ingest,
        "ingest_folder",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not re-ingest")),
    )
    result = ingest.scan_new(str(root), db_path=db_path)

    assert "DO001" in result["rebound"]
    conn = storage.connect(db_path)
    assert storage.get_order(conn, "DO001")["order_group"] == "Classic Orders"
    conn.close()


def test_scan_new_retags_order_moved_between_subfolders(tmp_path, monkeypatch):
    """An order moved from the classic to the machine subfolder is re-tagged,
    not re-ingested."""
    root = tmp_path / "EricProject"
    classic = root / "Classic Orders" / "DO001 ACME"
    classic.mkdir(parents=True)
    (classic / "Checklist DO001.docx").write_bytes(b"")

    db_path = str(tmp_path / "test.db")
    _patch_extraction(monkeypatch, classic, {"dossier_no": "DO001", "customer_name": "ACME"})
    ingest.scan_new(str(root), db_path=db_path)

    # Move the order folder into the machine subfolder.
    import shutil
    machine = root / "Machine Orders" / "DO001 ACME"
    machine.parent.mkdir(parents=True)
    shutil.move(str(classic), str(machine))
    shutil.rmtree(str(root / "Classic Orders"))

    monkeypatch.setattr(
        ingest,
        "ingest_folder",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not re-ingest")),
    )
    result = ingest.scan_new(str(root), db_path=db_path)

    assert result["ingested_count"] == 0
    assert "DO001" in result["rebound"]
    conn = storage.connect(db_path)
    storage.init_db(conn)
    order = storage.get_order(conn, "DO001")
    conn.close()
    assert order["order_group"] == "Machine Orders"
    assert order["source_folder"] == str(machine)


def test_refresh_order_keeps_existing_order_group(tmp_path, monkeypatch):
    root = tmp_path / "EricProject"
    classic = root / "Classic Orders" / "DO001 ACME"
    classic.mkdir(parents=True)
    (classic / "Checklist DO001.docx").write_bytes(b"")
    db_path = str(tmp_path / "test.db")

    _patch_extraction(monkeypatch, classic, {"dossier_no": "DO001", "customer_name": "ACME"})
    ingest.scan_new(str(root), db_path=db_path)

    _patch_extraction(monkeypatch, classic, {"dossier_no": "DO001", "industry": "Automotive"})
    result = ingest.refresh_order("DO001", db_path=db_path)

    assert result["order"]["order_group"] == "Classic Orders"
    assert result["order"]["industry"] == "Automotive"


def _make_overlapping_group_root(tmp_path):
    """Root where the machine folder also appears nested in the classic one.

    Mirrors the real SharePoint library: `New_Machines_Order_Folder` is exposed
    as its own top-level shortcut *and* lives inside `Order_Folders`.
    """
    root = tmp_path / "EricProject"
    classic = root / "Order_Folders" / "DO100 ACME"
    machine = root / "New_Machines_Order_Folder" / "New_Machines_Order_Folder" / "DO200 Globex"
    nested = root / "Order_Folders" / "New_Machines_Order_Folder" / "DO200 Globex"
    for folder in (classic, machine, nested):
        folder.mkdir(parents=True)
        (folder / "Checklist.docx").write_bytes(b"")
    return root, classic, machine, nested


def test_find_order_folders_by_group_skips_nested_other_group(tmp_path):
    root, classic, machine, nested = _make_overlapping_group_root(tmp_path)
    pairs = ingest.find_order_folders_by_group(str(root))

    assert (str(nested)) not in [folder for _, folder in pairs]
    assert ("New_Machines_Order_Folder", str(machine)) in pairs
    assert ("Order_Folders", str(classic)) in pairs
    assert len(pairs) == 2


def test_find_order_folders_by_group_allows_same_name_nesting(tmp_path):
    """The machine folder nested inside itself still counts as machine orders."""
    root, _, machine, _ = _make_overlapping_group_root(tmp_path)
    pairs = dict((folder, group) for group, folder in ingest.find_order_folders_by_group(str(root)))
    assert pairs[str(machine)] == "New_Machines_Order_Folder"


def test_find_order_folders_by_group_reports_each_order_once(tmp_path):
    root, _, _, _ = _make_overlapping_group_root(tmp_path)
    folders = [folder for _, folder in ingest.find_order_folders_by_group(str(root))]
    identities = [storage.folder_identity(f) for f in folders]
    assert len(identities) == len(set(identities))


def test_scan_new_tags_overlapping_machine_orders_to_machine_group(tmp_path, monkeypatch):
    root, _, machine, _ = _make_overlapping_group_root(tmp_path)
    db_path = str(tmp_path / "test.db")

    monkeypatch.setattr(
        "extract_checklist.find_checklist", lambda f: os.path.join(f, "Checklist.docx")
    )
    monkeypatch.setattr(
        "extract_checklist.extract",
        lambda p: {"dossier_no": os.path.basename(os.path.dirname(p)).split()[0]},
    )
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr("extract_order_pdf.find_shipping_pdfs", lambda f: [])

    result = ingest.scan_new(str(root), db_path=db_path)

    assert result["folders_found"] == 2
    conn = storage.connect(db_path)
    try:
        assert storage.get_order_group(conn, "DO200") == "New_Machines_Order_Folder"
        assert storage.get_order(conn, "DO200")["source_folder"] == str(machine)
        assert storage.get_order_group(conn, "DO100") == "Order_Folders"
    finally:
        conn.close()


def test_order_group_for_folder_derives_top_subfolder(tmp_path):
    root, _, machine = _make_two_group_root(tmp_path)
    assert ingest.order_group_for_folder(str(root), str(machine)) == "Machine Orders"


def test_order_group_for_folder_returns_none_outside_root(tmp_path):
    root, _, _ = _make_two_group_root(tmp_path)
    outside = tmp_path / "Elsewhere" / "DO500"
    assert ingest.order_group_for_folder(str(root), str(outside)) is None
    assert ingest.order_group_for_folder(str(root), str(root)) is None
    assert ingest.order_group_for_folder("", str(root)) is None


# ── shipping folder exists but nothing in it matched the filter ─────────────

def _patch_no_flow_extraction(monkeypatch, folder, dossier_no):
    monkeypatch.setattr(
        "extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx")
    )
    monkeypatch.setattr(
        "extract_checklist.extract", lambda p: {"dossier_no": dossier_no, "customer_name": "Corp"}
    )
    monkeypatch.setattr("extract_order_pdf.find_all_pdfs", lambda f: [])
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)


def test_ingest_folder_reports_unmatched_shipping_folder(tmp_path, monkeypatch):
    """The folder exists but holds only e.g. '1447745.pdf' — say so."""
    folder = tmp_path / "DO700 Bosch"
    shipping = folder / "Shipping Documents and Invoices"
    shipping.mkdir(parents=True)
    (shipping / "1447745.pdf").write_bytes(b"")
    _patch_no_flow_extraction(monkeypatch, folder, "DO700")

    def _must_not_run(dossier_no, folder):
        raise AssertionError("the shipping flow must not be triggered")

    monkeypatch.setattr("power_automate.trigger_shipping_date_flow", _must_not_run)

    db_path = str(tmp_path / "test.db")
    result = ingest.ingest_folder(str(folder), db_path=db_path)

    assert result["shipping_date_reason"] == ingest.NO_MATCHING_SHIPPING_DOCS_REASON
    conn = storage.connect(db_path)
    storage.init_db(conn)
    assert storage.get_order(conn, "DO700")["shipping_date_reason"] == (
        ingest.NO_MATCHING_SHIPPING_DOCS_REASON
    )
    conn.close()


def test_ingest_folder_stays_silent_without_a_shipping_folder(tmp_path, monkeypatch):
    folder = tmp_path / "DO701 Bosch"
    folder.mkdir()
    _patch_no_flow_extraction(monkeypatch, folder, "DO701")

    result = ingest.ingest_folder(str(folder), db_path=str(tmp_path / "test.db"))

    assert result.get("shipping_date_reason") is None


def test_ingest_folder_does_not_contradict_a_known_shipping_date(tmp_path, monkeypatch):
    """A date already on record must not be overwritten by the hint."""
    folder = tmp_path / "DO702 Bosch"
    shipping = folder / "Shipping Documents and Invoices"
    shipping.mkdir(parents=True)
    (shipping / "1447745.pdf").write_bytes(b"")
    db_path = str(tmp_path / "test.db")

    conn = storage.connect(db_path)
    storage.init_db(conn)
    storage.upsert_order(conn, {"dossier_no": "DO702", "shipping_date": "3/6/2026"})
    conn.close()

    _patch_no_flow_extraction(monkeypatch, folder, "DO702")
    result = ingest.ingest_folder(str(folder), db_path=db_path, merge="fill_empty")

    assert result.get("shipping_date_reason") is None
    conn = storage.connect(db_path)
    storage.init_db(conn)
    order = storage.get_order(conn, "DO702")
    conn.close()
    assert order["shipping_date"] == "3/6/2026"
    assert not order["shipping_date_reason"]


def test_refresh_order_shows_hint_for_unmatched_shipping_folder(tmp_path, monkeypatch):
    folder = tmp_path / "DO703 Bosch"
    shipping = folder / "Shipping Documents and Invoices"
    shipping.mkdir(parents=True)
    (shipping / "1447745.pdf").write_bytes(b"")
    db_path = str(tmp_path / "test.db")

    _patch_no_flow_extraction(monkeypatch, folder, "DO703")
    ingest.ingest_folder(str(folder), db_path=db_path)
    result = ingest.refresh_order("DO703", db_path=db_path)

    assert result["order"]["shipping_date_reason"] == ingest.NO_MATCHING_SHIPPING_DOCS_REASON
