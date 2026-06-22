"""
storage.py
----------
SQLite staging for extracted Checklist orders.

A single durable table `orders` keyed on `dossier_no` (the natural order key).
Re-running on the same order UPDATES the row instead of duplicating it, so the
Power Automate flow can run repeatedly without creating stale copies.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eric_orders.db")

# All columns we persist. Order-key first, then the extracted fields.
COLUMNS = [
    "dossier_no",
    "order_id",
    "account_no",
    "customer_name",
    "shipping_contact",
    "ship_to_address",
    "technical_contact",
    "order_date",
    "machine_type",
    "industry",
    "po_received_on",
    "customer_delivery_date_zru_oc",
    "eta_for_sa",
    "send_po_to_zrx",
    "send_order_acknowledgement",
    "received_oc_from_zrx",
    "oc_sent_to_customer",
    "packing_details_from_zrx",
    "iqoq",
    "installation_required_hours",
    "special_cal_gear_required",
    "technician",
    "service_activity_done_by",
    "sa",
    "source_file",
]


def connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    cols_sql = ",\n    ".join(f'"{c}" TEXT' for c in COLUMNS if c != "dossier_no")
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS orders (
            "dossier_no" TEXT PRIMARY KEY,
            {cols_sql},
            "updated_at" TEXT
        )
        """
    )
    conn.commit()


def upsert_order(conn: sqlite3.Connection, data: dict) -> str:
    """Insert or update one order. Returns the dossier_no used as key."""
    key = (data.get("dossier_no") or "").strip()
    if not key:
        raise ValueError("Cannot store order without a 'dossier_no' key.")

    record = {c: data.get(c) for c in COLUMNS}
    record["dossier_no"] = key
    record["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    all_cols = COLUMNS + ["updated_at"]
    placeholders = ", ".join(f":{c}" for c in all_cols)
    col_list = ", ".join(f'"{c}"' for c in all_cols)
    updates = ", ".join(f'"{c}"=excluded."{c}"' for c in all_cols if c != "dossier_no")

    conn.execute(
        f"""
        INSERT INTO orders ({col_list}) VALUES ({placeholders})
        ON CONFLICT("dossier_no") DO UPDATE SET {updates}
        """,
        record,
    )
    conn.commit()
    return key


def get_order(conn: sqlite3.Connection, dossier_no: str) -> dict | None:
    cur = conn.execute("SELECT * FROM orders WHERE dossier_no = ?", (dossier_no,))
    row = cur.fetchone()
    return dict(row) if row else None


def store(data: dict, db_path: str = DEFAULT_DB) -> str:
    conn = connect(db_path)
    try:
        init_db(conn)
        return upsert_order(conn, data)
    finally:
        conn.close()
