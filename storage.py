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
import re
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
    "collection_order_to_forwarder",
    "information_customer_cia",
    "invoice_received_from_zrx",
    "iqoq",
    "installation_required_hours",
    "special_cal_gear_required",
    "technician",
    "service_activity_done_by",
    "sa",
    "source_file",
    # --- From the Order Confirmation PDF (extract_order_pdf.py) ---
    "oc_source_file",
    "oc_purchase_order_no",
    "oc_quotation_no",
    "oc_dossier_no",
    "logistics_coordinator",
    "logistics_coordinator_phone",
    "logistics_coordinator_email",
    "rsm",
    "rsm_phone",
    "rsm_email",
    "source_folder",
    "shipping_date",
    "cancelled",
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS order_documents (
            "dossier_no" TEXT,
            "file_name" TEXT,
            "rel_path" TEXT,
            "category" TEXT,
            PRIMARY KEY ("dossier_no", "rel_path")
        )
        """
    )
    _migrate_columns(conn)
    conn.commit()


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Add any columns missing from a pre-existing `orders` table.

    SQLite's CREATE TABLE IF NOT EXISTS leaves an older table untouched, so new
    fields (e.g. the Order Confirmation contacts) must be added explicitly."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
    for col in COLUMNS + ["updated_at"]:
        if col not in existing:
            conn.execute(f'ALTER TABLE orders ADD COLUMN "{col}" TEXT')


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


_DATE_FORMATS = [
    "%m/%d/%Y %I:%M %p",   # 11/23/2021 2:20 PM
    "%-m/%-d/%Y %-I:%M %p", # non-zero-padded (Linux); ignored on Windows
    "%m/%d/%Y %H:%M",      # 11/23/2021 14:20
    "%d.%m.%Y %H:%M",      # 22.01.2026 14:48
    "%m/%d/%Y",            # 11/23/2021
    "%d.%m.%Y",            # 22.01.2026
]


def _parse_order_date(value: str | None) -> datetime:
    """Parse a mixed-format order_date string; returns datetime.min on failure."""
    if not value:
        return datetime.min
    s = re.sub(r"\s+", " ", value.strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.min


def list_orders(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute("SELECT * FROM orders")
    orders = [dict(r) for r in cur.fetchall()]
    orders.sort(key=lambda o: _parse_order_date(o.get("order_date")), reverse=True)
    return orders


def replace_documents(conn: sqlite3.Connection, dossier_no: str, docs: list[dict]) -> None:
    """Replace the document list for an order. Each doc: {file_name, rel_path, category}."""
    conn.execute("DELETE FROM order_documents WHERE dossier_no = ?", (dossier_no,))
    conn.executemany(
        """INSERT OR REPLACE INTO order_documents
           (dossier_no, file_name, rel_path, category) VALUES (?, ?, ?, ?)""",
        [(dossier_no, d.get("file_name"), d.get("rel_path"), d.get("category")) for d in docs],
    )
    conn.commit()


def get_documents(conn: sqlite3.Connection, dossier_no: str) -> list[dict]:
    cur = conn.execute(
        "SELECT file_name, rel_path, category FROM order_documents WHERE dossier_no = ? ORDER BY category, file_name",
        (dossier_no,),
    )
    return [dict(r) for r in cur.fetchall()]


def list_source_folders(conn: sqlite3.Connection) -> set[str]:
    """Return the set of all known source_folder values stored in the DB."""
    cur = conn.execute("SELECT source_folder FROM orders WHERE source_folder IS NOT NULL")
    return {row[0] for row in cur.fetchall()}


def store(data: dict, db_path: str = DEFAULT_DB) -> str:
    conn = connect(db_path)
    try:
        init_db(conn)
        return upsert_order(conn, data)
    finally:
        conn.close()
