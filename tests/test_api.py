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
