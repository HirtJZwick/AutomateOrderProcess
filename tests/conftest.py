import pytest
import sqlite3
from unittest.mock import patch
import storage


@pytest.fixture
def db():
    """In-memory SQLite connection, schema already initialized."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    storage.init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_order():
    """A minimal valid order dict."""
    return {
        "dossier_no": "TEST001",
        "customer_name": "ACME Corp",
        "machine_type": "Z010",
        "order_date": "1/15/2026",
        "source_folder": r"C:\fake\TEST001 ACME",
    }


@pytest.fixture
def test_db_path(tmp_path):
    """Temp file-based DB with schema initialized. Shared with api_client."""
    path = str(tmp_path / "test.db")
    conn = storage.connect(path)
    storage.init_db(conn)
    conn.close()
    return path


@pytest.fixture
def api_client(test_db_path, tmp_path):
    """FastAPI TestClient patched to use a temp DB and root folder."""
    cfg = {"root_folder": str(tmp_path), "db_path": test_db_path}
    with patch("webapp.backend.app.load_config", return_value=cfg):
        from fastapi.testclient import TestClient
        from webapp.backend.app import app
        yield TestClient(app)