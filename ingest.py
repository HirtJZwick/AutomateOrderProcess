"""
ingest.py
---------
Core ingestion for the order-tracking platform.

`ingest_folder(folder)` extracts a single order from its document folder
(Checklist .docx enriched with the Order Confirmation PDF), records which
documents are present, and writes to the SQLite database.

Write modes
-----------
merge="overwrite" (default) — full upsert, replaces all columns.
merge="fill_empty"          — only fills columns that are currently empty/NULL;
                              manually edited values are never clobbered.
                              Documents are always refreshed in both modes.

`refresh_order(dossier_no)` re-scans the stored source_folder in fill_empty
mode — new documents appear, no existing field values are overwritten.

`scan_root(root)` walks a configured root directory, finds every order folder
(any folder containing a `Checklist*.docx`), and ingests them all.

This module reuses the existing extraction code and is the ONLY write path the
web platform uses - the Excel write-back lives separately in `excel_legacy/`.
"""
from __future__ import annotations

import glob
import os

import extract_checklist
import extract_order_pdf
import llm_extract
import storage

# Filename-substring -> document category, for the documents list / completeness.
_DOC_CATEGORIES = [
    ("checklist", "Checklist"),
    ("order confirmation", "Order Confirmation"),
    ("zru oc", "ZRU Order Confirmation"),
    ("zru order", "ZRU Order"),
    ("accessories", "Accessories Quote"),
    ("invoice", "Invoice"),
    ("packing", "Packing / Shipping"),
    ("shipping", "Packing / Shipping"),
    ("order report", "Checklist"),
]


def categorize(file_name: str) -> str:
    low = file_name.lower()
    for sub, cat in _DOC_CATEGORIES:
        if sub in low:
            return cat
    return "Other"


def list_documents(folder: str) -> list[dict]:
    """All files in the order folder (including subfolders), categorized."""
    docs = []
    for p in glob.glob(os.path.join(folder, "**", "*"), recursive=True):
        if not os.path.isfile(p):
            continue
        name = os.path.basename(p)
        if name.startswith("~$"):
            continue
        docs.append(
            {
                "file_name": name,
                "rel_path": os.path.relpath(p, folder).replace("\\", "/"),
                "category": categorize(name),
            }
        )
    return docs


def ingest_folder(
    folder: str,
    db_path: str = storage.DEFAULT_DB,
    merge: str = "overwrite",
) -> dict | None:
    """Extract one order from `folder` and write it to the DB.

    Args:
        folder:  Path to the order folder.
        db_path: Path to the SQLite database.
        merge:   "overwrite" (default) — full upsert, replaces all columns.
                 "fill_empty" — only fills columns that are currently empty/NULL
                 in the DB; manually edited values are never clobbered.
                 Documents are always refreshed regardless of merge mode.

    Returns the extracted data dict, or None if no checklist was found/parsed.
    """
    checklist = extract_checklist.find_checklist(folder)
    if not checklist:
        return None

    data = extract_checklist.extract(checklist)
    if not data.get("dossier_no"):
        return None

    order_pdf = extract_order_pdf.find_order_pdf(folder)
    if order_pdf:
        data.update(extract_order_pdf.extract(order_pdf))     # header (PO, quotation)
        try:
            data.update(llm_extract.extract_order_contacts(order_pdf))  # contacts via LLM
        except Exception as exc:
            print(f"WARN: contact extraction failed for {order_pdf}: {exc}")

    for shipping_pdf in extract_order_pdf.find_shipping_pdfs(folder):
        try:
            result = llm_extract.extract_shipping_date(shipping_pdf)
        except Exception as exc:
            print(f"WARN: shipping date extraction failed for {shipping_pdf}: {exc}")
            continue
        if result.get("shipping_date"):
            data.update(result)
            break

    data["source_folder"] = folder
    if "cancelled" in os.path.basename(folder).lower():
        data["cancelled"] = "1"

    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        key = data["dossier_no"]
        if merge == "fill_empty":
            storage.fill_empty_fields(conn, key, data)
        else:
            storage.upsert_order(conn, data)
        storage.replace_documents(conn, key, list_documents(folder))
    finally:
        conn.close()
    return data


def refresh_order(
    dossier_no: str,
    db_path: str = storage.DEFAULT_DB,
) -> dict:
    """Re-scan the order's source folder, filling only empty DB fields.

    Manually edited (or previously extracted) field values are never overwritten.
    Documents are always refreshed so newly added files (invoices, shipping docs)
    become visible immediately.

    Args:
        dossier_no: The order primary key.
        db_path:    Path to the SQLite database.

    Returns:
        {"order": <order dict>, "documents": [<doc dicts>]}

    Raises:
        ValueError: if the order is not found, or its source_folder is missing
                    or no longer present on disk.
    """
    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        order = storage.get_order(conn, dossier_no)
        if order is None:
            raise ValueError(f"Order {dossier_no!r} not found in database.")
        folder = (order.get("source_folder") or "").strip()
        if not folder or not os.path.isdir(folder):
            raise ValueError(
                f"Order {dossier_no!r} has no valid source_folder on disk: {folder!r}"
            )
    finally:
        conn.close()

    ingest_folder(folder, db_path=db_path, merge="fill_empty")

    conn = storage.connect(db_path)
    try:
        updated_order = storage.get_order(conn, dossier_no)
        documents = storage.get_documents(conn, dossier_no)
    finally:
        conn.close()

    return {"order": updated_order, "documents": documents}


def find_order_folders(root: str) -> list[str]:
    """Every distinct folder under `root` that contains a Checklist*.docx."""
    folders = set()
    for p in glob.glob(os.path.join(root, "**", "Checklist*.docx"), recursive=True):
        if not os.path.basename(p).startswith("~$"):
            folders.add(os.path.dirname(p))
    return sorted(folders)


def scan_new(root: str, db_path: str = storage.DEFAULT_DB) -> dict:
    """Ingest only order folders not yet present in the database.

    Compares on-disk folders (by path) against the `source_folder` values
    already stored.  Folders already in the DB are skipped entirely.
    """
    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        known = storage.list_source_folders(conn)
    finally:
        conn.close()

    all_folders = find_order_folders(root)
    new_folders = [f for f in all_folders if f not in known]

    ingested, skipped = [], []
    aborted = None
    for folder in new_folders:
        try:
            order = ingest_folder(folder, db_path=db_path)
            if order:
                ingested.append(order.get("dossier_no"))
            else:
                skipped.append(folder)
        except Exception as exc:
            aborted = str(exc)
            break  # stop — no requests left
    result = {
        "root": root,
        "folders_found": len(all_folders),
        "new_folders_found": len(new_folders),
        "ingested": ingested,
        "ingested_count": len(ingested),
        "skipped": skipped,
    }
    if aborted:
        result["aborted"] = aborted
    return result


def scan_root(root: str, db_path: str = storage.DEFAULT_DB) -> dict:
    """Ingest every order folder under `root`. Returns a summary dict."""
    folders = find_order_folders(root)
    ingested, skipped = [], []
    aborted = None
    for folder in folders:
        try:
            order = ingest_folder(folder, db_path=db_path)
            if order:
                ingested.append(order.get("dossier_no"))
            else:
                skipped.append(folder)
        except Exception as exc:
            aborted = str(exc)
            break  # stop — no requests left
    result = {
        "root": root,
        "folders_found": len(folders),
        "ingested": ingested,
        "ingested_count": len(ingested),
        "skipped": skipped,
    }
    if aborted:
        result["aborted"] = aborted
    return result


if __name__ == "__main__":
    import json
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "."
    if os.path.isdir(target) and extract_checklist.find_checklist(target):
        print(json.dumps(ingest_folder(target), indent=2, ensure_ascii=False, default=str))
    else:
        print(json.dumps(scan_root(target), indent=2, ensure_ascii=False, default=str))
