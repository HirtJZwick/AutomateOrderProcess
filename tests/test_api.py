import pytest
import storage
from unittest.mock import patch


def test_get_config(api_client):
    res = api_client.get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert "root_folder" in body
    assert "db_path" in body


def test_get_orders_empty(api_client):
    res = api_client.get("/api/orders")
    assert res.status_code == 200
    body = res.json()
    assert body["orders"] == []
    assert body["count"] == 0


def test_get_order_not_found(api_client):
    res = api_client.get("/api/orders/DOESNOTEXIST")
    assert res.status_code == 404


def test_get_order_found(api_client, test_db_path):
    conn = storage.connect(test_db_path)
    storage.upsert_order(conn, {
        "dossier_no": "D001",
        "customer_name": "Test Corp",
        "order_date": "1/1/2026",
    })
    conn.close()

    res = api_client.get("/api/orders/D001")
    assert res.status_code == 200
    body = res.json()
    assert body["order"]["customer_name"] == "Test Corp"
    assert "stage" in body
    assert "completeness" in body


def test_get_orders_includes_stage(api_client, test_db_path):
    conn = storage.connect(test_db_path)
    storage.upsert_order(conn, {"dossier_no": "D002", "shipping_date": "5/15/2026"})
    conn.close()

    res = api_client.get("/api/orders")
    assert res.status_code == 200
    orders = res.json()["orders"]
    assert orders[0]["stage"]["name"] == "Shipped"


def test_scan_empty_folder_returns_summary(api_client):
    # tmp_path has no Checklist files → folders_found == 0
    res = api_client.post("/api/scan")
    assert res.status_code == 200
    body = res.json()
    assert body["folders_found"] == 0
    assert body["ingested_count"] == 0


def test_scan_invalid_root_returns_400(api_client):
    bad_cfg = {"root_folder": r"C:\nonexistent\does_not_exist", "db_path": ":memory:"}
    with patch("webapp.backend.app.load_config", return_value=bad_cfg):
        res = api_client.post("/api/scan")
    assert res.status_code == 400


def test_update_config_returns_root_folder(api_client, tmp_path):
    with patch("webapp.backend.app.save_config"):
        res = api_client.post("/api/config", json={"root_folder": str(tmp_path)})
    assert res.status_code == 200
    assert res.json()["root_folder"] == str(tmp_path)


# ── PATCH /api/orders/{dossier} ───────────────────────────────────────────────

def test_patch_order_updates_field(api_client, test_db_path):
    conn = storage.connect(test_db_path)
    storage.upsert_order(conn, {"dossier_no": "D010", "customer_name": "Old Name"})
    conn.close()

    res = api_client.patch("/api/orders/D010", json={"fields": {"customer_name": "New Name"}})
    assert res.status_code == 200
    body = res.json()
    assert body["order"]["customer_name"] == "New Name"
    assert "stage" in body
    assert "completeness" in body
    assert "documents" in body


def test_patch_order_not_found_returns_404(api_client):
    res = api_client.patch("/api/orders/DOESNOTEXIST", json={"fields": {"customer_name": "X"}})
    assert res.status_code == 404


def test_patch_order_ignores_immutable_fields(api_client, test_db_path):
    conn = storage.connect(test_db_path)
    storage.upsert_order(conn, {"dossier_no": "D011", "customer_name": "Corp"})
    conn.close()

    res = api_client.patch("/api/orders/D011", json={"fields": {"dossier_no": "HACKED"}})
    assert res.status_code == 200
    assert res.json()["order"]["dossier_no"] == "D011"


def test_patch_order_allows_clearing_field(api_client, test_db_path):
    conn = storage.connect(test_db_path)
    storage.upsert_order(conn, {"dossier_no": "D012", "customer_name": "Corp", "industry": "Medical"})
    conn.close()

    res = api_client.patch("/api/orders/D012", json={"fields": {"industry": ""}})
    assert res.status_code == 200
    assert res.json()["order"]["industry"] == ""


# ── POST /api/orders/{dossier}/refresh ───────────────────────────────────────

def test_refresh_order_returns_updated_order(api_client, test_db_path, tmp_path, monkeypatch):
    folder = tmp_path / "DO020 Corp"
    folder.mkdir()
    (folder / "Checklist.docx").write_bytes(b"")

    conn = storage.connect(test_db_path)
    storage.upsert_order(conn, {
        "dossier_no": "DO020",
        "customer_name": "Corp",
        "source_folder": str(folder),
    })
    conn.close()

    monkeypatch.setattr("extract_checklist.find_checklist", lambda f: str(folder / "Checklist.docx"))
    monkeypatch.setattr("extract_checklist.extract", lambda p: {"dossier_no": "DO020", "industry": "Automotive"})
    monkeypatch.setattr("extract_order_pdf.find_order_pdf", lambda f: None)
    monkeypatch.setattr("extract_order_pdf.find_shipping_pdfs", lambda f: [])

    res = api_client.post("/api/orders/DO020/refresh")
    assert res.status_code == 200
    body = res.json()
    assert body["order"]["industry"] == "Automotive"
    assert body["order"]["customer_name"] == "Corp"  # not overwritten
    assert "documents" in body
    assert "stage" in body
    assert "completeness" in body


def test_refresh_order_not_found_returns_400(api_client):
    res = api_client.post("/api/orders/DOESNOTEXIST/refresh")
    assert res.status_code == 400


def test_refresh_order_missing_folder_returns_400(api_client, test_db_path):
    conn = storage.connect(test_db_path)
    storage.upsert_order(conn, {
        "dossier_no": "DO021",
        "source_folder": r"C:\nonexistent\path\that\does\not\exist",
    })
    conn.close()

    res = api_client.post("/api/orders/DO021/refresh")
    assert res.status_code == 400
