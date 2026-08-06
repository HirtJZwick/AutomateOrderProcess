"""
storage.py
----------
SQLite staging for extracted Checklist orders.

A single durable table `orders` keyed on `dossier_no` (the natural order key).
Re-running on the same order UPDATES the row instead of duplicating it, so the
Power Automate flow can run repeatedly without creating stale copies.

Public write functions
----------------------
upsert_order       -- full insert-or-overwrite (first-time ingestion)
update_order_fields -- partial update from manual UI edits (never overwrites
                       dossier_no / updated_at; allows clearing fields)
fill_empty_fields   -- refresh-safe merge: only fills columns that are currently
                       empty, so manually edited values are never clobbered
"""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eric_orders.db")


def folder_identity(path: str) -> str:
    """Normalized identity key for an order folder: final folder name only.

    The same shared SharePoint order folder can appear under different
    OneDrive synchronization roots for different users (e.g. `C:\\Users\\Hirtj\\
    OneDrive - ...\\EricProject\\DO860728 Acom Labs OPP450766` vs. `C:\\Users\\
    MilanE\\OneDrive - ...\\EricProject\\DO860728 Acom Labs OPP450766`), so the
    full absolute path is not a stable identity. Only the final folder name is
    compared, normalized for case and trailing separators (Windows semantics).

    Used by `ingest.scan_new`/`ingest._folder_identity` to match on-disk
    folders against known orders, and by `excel_sync.py` to match rows in the
    shared Excel workbooks back to a local order folder.
    """
    name = os.path.basename(os.path.normpath(path))
    return os.path.normcase(name)

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
    # Name of the immediate subfolder of the configured root that the order
    # folder was found in (e.g. "Classic Orders" / "Machine Orders"). Set by
    # ingest.scan_root / ingest.scan_new; blank for orders ingested before
    # this field existed, until the next scan rebinds them.
    "order_group",
    "shipping_date",
    "shipping_date_reason",
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
    orders.sort(
        key=lambda o: _parse_order_date(o.get("shipping_date") or o.get("order_date")),
        reverse=True,
    )
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


def list_dossier_source_folders(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Return (dossier_no, source_folder) pairs for every order with a folder.

    Used by `ingest.scan_new` to match on-disk folders against known orders by
    their final folder name (not the full path), since the same shared
    SharePoint order folder can appear under different OneDrive roots for
    different users.
    """
    cur = conn.execute(
        "SELECT dossier_no, source_folder FROM orders "
        "WHERE source_folder IS NOT NULL AND source_folder != ''"
    )
    return [(row[0], row[1]) for row in cur.fetchall()]


def update_source_folder(
    conn: sqlite3.Connection,
    dossier_no: str,
    source_folder: str,
    order_group: str | None = None,
) -> None:
    """Rebind an existing order's `source_folder` to a new path.

    Used when the same order folder (matched by final folder name) is found
    under a different OneDrive synchronization root than what is currently
    stored. Only `source_folder`, optionally `order_group`, and `updated_at`
    are touched — no other extracted or manually edited fields are affected.

    `order_group` is passed when the scan knows which root subfolder the order
    now lives in, so orders that moved between subfolders (or predate the
    column) get re-tagged. Pass None to leave the stored value untouched.
    """
    columns = {"source_folder": source_folder}
    if order_group is not None:
        columns["order_group"] = order_group
    set_clause = ", ".join(f'"{k}"=?' for k in columns)
    conn.execute(
        f'UPDATE orders SET {set_clause}, "updated_at"=? WHERE "dossier_no"=?',
        (*columns.values(), datetime.now(timezone.utc).isoformat(timespec="seconds"), dossier_no),
    )
    conn.commit()


def get_order_group(conn: sqlite3.Connection, dossier_no: str) -> str | None:
    """Return the stored `order_group` for an order, or None when unset."""
    cur = conn.execute(
        'SELECT "order_group" FROM orders WHERE "dossier_no"=?', (dossier_no,)
    )
    row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Partial-update helpers (isolation point for future DB backend swaps)
# ---------------------------------------------------------------------------

_IMMUTABLE = {"dossier_no", "updated_at"}
_EDITABLE = set(COLUMNS) - _IMMUTABLE


def _is_empty(value) -> bool:
    """True when a DB value is absent or blank — used by fill_empty_fields."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def _update_columns(conn: sqlite3.Connection, dossier_no: str, updates: dict) -> None:
    """Run a partial UPDATE for `updates` plus a fresh `updated_at`. No-op when empty.

    This is the only place partial-update SQL exists; both public helpers call it
    so a future backend swap only needs to reimplement this one function.
    """
    if not updates:
        return
    params = dict(updates)
    params["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    set_clause = ", ".join(f'"{k}"=:{k}' for k in params)
    params["_key"] = dossier_no
    conn.execute(
        f'UPDATE orders SET {set_clause} WHERE "dossier_no"=:_key',
        params,
    )
    conn.commit()


def update_order_fields(
    conn: sqlite3.Connection, dossier_no: str, fields: dict
) -> dict | None:
    """Persist manual edits from the UI drawer.

    Rules:
    - Only keys listed in COLUMNS (minus dossier_no and updated_at) are written.
    - Empty/blank submitted values ARE written — clearing a field blanks it.
    - Returns the updated order dict, or None if the order does not exist.
    """
    if get_order(conn, dossier_no) is None:
        return None

    updates = {k: v for k, v in fields.items() if k in _EDITABLE}
    if not updates:
        return get_order(conn, dossier_no)

    _update_columns(conn, dossier_no, updates)
    return get_order(conn, dossier_no)


def fill_empty_fields(
    conn: sqlite3.Connection, dossier_no: str, data: dict, force_fields: set[str] | None = None
) -> dict | None:
    """Merge extracted data into an existing order, filling only empty columns.

    Used by the per-order refresh so that manually edited (or previously
    extracted) values are never overwritten. Documents are handled separately
    by replace_documents.

    `force_fields` names columns that are always overwritten with the latest
    extracted value (when non-empty), even if the DB already holds a value —
    used for system-derived fields that are never manually edited (e.g.
    `shipping_date_reason`, which must track the *current* explanation from
    the flow rather than getting stuck on a stale one).

    If the order row does not yet exist, falls back to a full upsert_order.
    Returns the resulting order dict.
    """
    current = get_order(conn, dossier_no)
    if current is None:
        upsert_order(conn, data)
        return get_order(conn, dossier_no)

    force_fields = force_fields or set()
    updates = {
        k: data[k]
        for k in _EDITABLE
        if k in data and not _is_empty(data.get(k))
        and (k in force_fields or _is_empty(current.get(k)))
    }
    _update_columns(conn, dossier_no, updates)
    return get_order(conn, dossier_no)


def store(data: dict, db_path: str = DEFAULT_DB) -> str:
    conn = connect(db_path)
    try:
        init_db(conn)
        return upsert_order(conn, data)
    finally:
        conn.close()
