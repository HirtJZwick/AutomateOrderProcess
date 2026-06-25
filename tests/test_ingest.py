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
