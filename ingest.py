"""
ingest.py
---------
Core ingestion for the order-tracking platform.

`ingest_folder(folder)` extracts a single order from its document folder
(Checklist .docx enriched with the Order Confirmation PDF), records which
documents are present, and upserts everything into the SQLite database.

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


def ingest_folder(folder: str, db_path: str = storage.DEFAULT_DB) -> dict | None:
    """Extract one order from `folder` and upsert it. Returns the order dict,
    or None if no checklist could be parsed into a dossier key."""
    checklist = extract_checklist.find_checklist(folder)
    if not checklist:
        return None

    data = extract_checklist.extract(checklist)
    if not data.get("dossier_no"):
        return None

    """ order_pdf = extract_order_pdf.find_order_pdf(folder)
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
            break """

    data["source_folder"] = folder

    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        key = storage.upsert_order(conn, data)
        storage.replace_documents(conn, key, list_documents(folder))
    finally:
        conn.close()
    return data


def find_order_folders(root: str) -> list[str]:
    """Every distinct folder under `root` that contains a Checklist*.docx."""
    folders = set()
    for p in glob.glob(os.path.join(root, "**", "Checklist*.docx"), recursive=True):
        if not os.path.basename(p).startswith("~$"):
            folders.add(os.path.dirname(p))
    return sorted(folders)


def scan_root(root: str, db_path: str = storage.DEFAULT_DB) -> dict:
    """Ingest every order folder under `root`. Returns a summary dict."""
    folders = find_order_folders(root)
    ingested, skipped = [], []
    for folder in folders:
        try:
            order = ingest_folder(folder, db_path=db_path)
            if order:
                ingested.append(order.get("dossier_no"))
            else:
                skipped.append(folder)
        except Exception as exc:  # keep scanning even if one folder is bad
            skipped.append(f"{folder} :: {exc}")
    return {
        "root": root,
        "folders_found": len(folders),
        "ingested": ingested,
        "ingested_count": len(ingested),
        "skipped": skipped,
    }


if __name__ == "__main__":
    import json
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "."
    if os.path.isdir(target) and extract_checklist.find_checklist(target):
        print(json.dumps(ingest_folder(target), indent=2, ensure_ascii=False, default=str))
    else:
        print(json.dumps(scan_root(target), indent=2, ensure_ascii=False, default=str))
