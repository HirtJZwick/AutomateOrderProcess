import pytest
import ingest
import storage


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


# ── ingest_folder merge modes ─────────────────────────────────────────────────

def _patch_extraction(monkeypatch, folder, extracted_data):
    """Helper: patch both checklist finders to return `extracted_data`."""
    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: dict(extracted_data))
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
