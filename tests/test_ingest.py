import pytest
import ingest
import extract_order_pdf
import storage


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
        lambda folder: {
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
        lambda folder: {
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
    monkeypatch.setattr("excel_sync.lookup_shipping_date", lambda folder: {})
    monkeypatch.setattr(
        "excel_sync.lookup_latest_shipping_result",
        lambda: {
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
    monkeypatch.setattr("excel_sync.lookup_shipping_date", lambda folder: {})

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
        lambda folder: {
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
        lambda folder: {
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
        lambda folder: {
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
        lambda folder: {"logistics_coordinator": "Jane Doe", "rsm": "John Smith"},
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

    def _fail_if_called(folder):
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


# ── scan_new: folder-name identity across different OneDrive roots ──────────

def test_scan_new_skips_known_order_with_different_root_path(tmp_path, monkeypatch):
    """Same order folder name under a different OneDrive-style root must be
    recognized as already known, not re-ingested."""
    # Simulate Milan's OneDrive root, already ingested.
    milan_root = tmp_path / "MilanE" / "OneDrive" / "EricProject"
    milan_root.mkdir(parents=True)
    milan_folder = milan_root / "DO860728 Acom Labs OPP450766"
    milan_folder.mkdir()
    (milan_folder / "Checklist DO860728.docx").write_bytes(b"")

    db_path = str(tmp_path / "test.db")
    _patch_extraction(monkeypatch, milan_folder, {"dossier_no": "DO860728", "customer_name": "Acom Labs"})
    ingest.ingest_folder(str(milan_folder), db_path=db_path)

    # Now simulate Eric's OneDrive root with the SAME final folder name.
    eric_root = tmp_path / "Hirtj" / "OneDrive" / "EricProject"
    eric_root.mkdir(parents=True)
    eric_folder = eric_root / "DO860728 Acom Labs OPP450766"
    eric_folder.mkdir()
    (eric_folder / "Checklist DO860728.docx").write_bytes(b"")

    def _fail_if_called(folder, **kwargs):
        raise AssertionError("ingest_folder should not be called for a known folder name")

    monkeypatch.setattr(ingest, "ingest_folder", _fail_if_called)

    result = ingest.scan_new(str(eric_root), db_path=db_path)

    assert result["new_folders_found"] == 0
    assert result["ingested_count"] == 0


def test_scan_new_rebinds_source_folder_to_current_path(tmp_path, monkeypatch):
    """When the matching order is found at a different absolute path, the
    stored source_folder must be updated to the currently scanned path."""
    milan_root = tmp_path / "MilanE" / "OneDrive" / "EricProject"
    milan_root.mkdir(parents=True)
    milan_folder = milan_root / "DO860728 Acom Labs OPP450766"
    milan_folder.mkdir()
    (milan_folder / "Checklist DO860728.docx").write_bytes(b"")

    db_path = str(tmp_path / "test.db")
    _patch_extraction(monkeypatch, milan_folder, {"dossier_no": "DO860728", "customer_name": "Acom Labs"})
    ingest.ingest_folder(str(milan_folder), db_path=db_path)

    eric_root = tmp_path / "Hirtj" / "OneDrive" / "EricProject"
    eric_root.mkdir(parents=True)
    eric_folder = eric_root / "DO860728 Acom Labs OPP450766"
    eric_folder.mkdir()
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
    milan_root.mkdir(parents=True)
    milan_folder = milan_root / "DO860728 Acom Labs OPP450766"
    milan_folder.mkdir()
    (milan_folder / "Checklist DO860728.docx").write_bytes(b"")

    db_path = str(tmp_path / "test.db")
    _patch_extraction(monkeypatch, milan_folder, {"dossier_no": "DO860728", "customer_name": "Acom Labs"})
    ingest.ingest_folder(str(milan_folder), db_path=db_path)

    eric_root = tmp_path / "Hirtj" / "OneDrive" / "EricProject"
    eric_root.mkdir(parents=True)
    eric_folder = eric_root / "DO860728 Acom Labs OPP450766"
    eric_folder.mkdir()
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
    root.mkdir()
    folder = root / "DO999999 New Customer"
    folder.mkdir()
    (folder / "Checklist DO999999.docx").write_bytes(b"")

    db_path = str(tmp_path / "test.db")
    _patch_extraction(monkeypatch, folder, {"dossier_no": "DO999999", "customer_name": "New Customer"})

    result = ingest.scan_new(str(root), db_path=db_path)

    assert result["new_folders_found"] == 1
    assert result["ingested"] == ["DO999999"]


def test_scan_new_folder_name_matching_is_case_insensitive(tmp_path, monkeypatch):
    milan_root = tmp_path / "MilanE" / "EricProject"
    milan_root.mkdir(parents=True)
    milan_folder = milan_root / "do860728 acom labs opp450766"
    milan_folder.mkdir()
    (milan_folder / "Checklist DO860728.docx").write_bytes(b"")

    db_path = str(tmp_path / "test.db")
    _patch_extraction(monkeypatch, milan_folder, {"dossier_no": "DO860728", "customer_name": "Acom Labs"})
    ingest.ingest_folder(str(milan_folder), db_path=db_path)

    eric_root = tmp_path / "Hirtj" / "EricProject"
    eric_root.mkdir(parents=True)
    eric_folder = eric_root / "DO860728 ACOM LABS OPP450766"
    eric_folder.mkdir()
    (eric_folder / "Checklist DO860728.docx").write_bytes(b"")

    result = ingest.scan_new(str(eric_root), db_path=db_path)

    assert result["new_folders_found"] == 0
    assert result["ingested_count"] == 0


def test_folder_identity_ignores_trailing_separator():
    assert ingest._folder_identity(r"C:\root\DO001 ACME" + "\\") == ingest._folder_identity(r"C:\root\DO001 ACME")
