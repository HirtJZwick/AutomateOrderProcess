import pytest
import storage


def test_upsert_creates_order(db, sample_order):
    storage.upsert_order(db, sample_order)
    result = storage.get_order(db, "TEST001")
    assert result is not None
    assert result["customer_name"] == "ACME Corp"


def test_upsert_updates_existing(db, sample_order):
    storage.upsert_order(db, sample_order)
    sample_order["customer_name"] = "Updated Corp"
    storage.upsert_order(db, sample_order)
    assert storage.get_order(db, "TEST001")["customer_name"] == "Updated Corp"


def test_upsert_requires_dossier_no(db):
    with pytest.raises(ValueError, match="dossier_no"):
        storage.upsert_order(db, {"customer_name": "Orphan"})


def test_get_order_returns_none_for_missing(db):
    assert storage.get_order(db, "DOESNOTEXIST") is None


def test_list_orders_empty_db(db):
    assert storage.list_orders(db) == []


def test_list_orders_returns_all(db, sample_order):
    storage.upsert_order(db, sample_order)
    orders = storage.list_orders(db)
    assert len(orders) == 1
    assert orders[0]["dossier_no"] == "TEST001"


def test_list_orders_sorted_newest_first(db):
    storage.upsert_order(db, {"dossier_no": "OLD", "order_date": "1/01/2024"})
    storage.upsert_order(db, {"dossier_no": "NEW", "order_date": "6/01/2026"})
    storage.upsert_order(db, {"dossier_no": "MID", "order_date": "3/15/2025"})
    orders = storage.list_orders(db)
    assert [o["dossier_no"] for o in orders] == ["NEW", "MID", "OLD"]


def test_list_orders_mixed_date_formats(db):
    # European DD.MM.YYYY (22 Jan 2026) should sort before US M/DD/YYYY (15 Jan 2026)
    storage.upsert_order(db, {"dossier_no": "EURO", "order_date": "22.01.2026 14:48"})
    storage.upsert_order(db, {"dossier_no": "US", "order_date": "1/15/2026 10:00 AM"})
    orders = storage.list_orders(db)
    assert orders[0]["dossier_no"] == "EURO"


def test_list_orders_null_date_sorts_last(db):
    storage.upsert_order(db, {"dossier_no": "NODATE", "order_date": None})
    storage.upsert_order(db, {"dossier_no": "DATED", "order_date": "1/01/2026"})
    orders = storage.list_orders(db)
    assert orders[0]["dossier_no"] == "DATED"
    assert orders[-1]["dossier_no"] == "NODATE"


def test_replace_and_get_documents(db, sample_order):
    storage.upsert_order(db, sample_order)
    docs = [
        {"file_name": "Checklist.docx", "rel_path": "Checklist.docx", "category": "Checklist"},
        {"file_name": "Invoice.pdf", "rel_path": "Invoice.pdf", "category": "Invoice"},
    ]
    storage.replace_documents(db, "TEST001", docs)
    result = storage.get_documents(db, "TEST001")
    assert len(result) == 2
    assert {d["file_name"] for d in result} == {"Checklist.docx", "Invoice.pdf"}


def test_replace_documents_is_idempotent(db, sample_order):
    storage.upsert_order(db, sample_order)
    docs = [{"file_name": "Checklist.docx", "rel_path": "Checklist.docx", "category": "Checklist"}]
    storage.replace_documents(db, "TEST001", docs)
    storage.replace_documents(db, "TEST001", docs)
    assert len(storage.get_documents(db, "TEST001")) == 1


def test_upsert_replaces_all_fields(db, sample_order):
    storage.upsert_order(db, sample_order)
    storage.upsert_order(db, {"dossier_no": "TEST001", "machine_type": "Z050"})
    result = storage.get_order(db, "TEST001")
    assert result["machine_type"] == "Z050"
    assert result["customer_name"] is None
