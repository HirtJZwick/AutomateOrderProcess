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

`scan_new(root)` does the same walk but only ingests folders whose final
folder name (e.g. "DO860728 Acom Labs OPP450766") is not already known in the
database. Order folders live on a shared SharePoint location synchronized via
OneDrive, so the same order can appear under a different absolute path for
each user (different OneDrive root). Matching by full path would therefore
treat an already-ingested order as new; matching by final folder name (case-
insensitive) correctly recognizes it and instead rebinds the stored
`source_folder` to the path found in the current scan, so Refresh keeps
working from that user's machine.

Contacts (logistics coordinator, RSM) and the shipping date are no longer
extracted locally by an LLM. Instead `power_automate.py` triggers the two
Power Automate flows that read the order's documents themselves and write
results to two shared Excel workbooks; `excel_sync.py` then reads those
workbooks back and merges the results into the order (fill-empty semantics
via the "fill_empty" merge mode, same as any other field).

This module is the ONLY write path the web platform uses.
"""
from __future__ import annotations

import glob
import os

import excel_sync
import extract_checklist
import extract_order_pdf
import power_automate
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

    # Header (PO/quotation numbers) — run regex over all PDFs, fill-empty merge
    for pdf in extract_order_pdf.find_all_pdfs(folder):
        for k, v in extract_order_pdf.extract(pdf).items():
            if not data.get(k):
                data[k] = v

    # Contacts — Power Automate flow reads the OC PDFs itself and writes the
    # result to the shared OC_Contacts.xlsx workbook; we then read it back.
    all_pdfs = extract_order_pdf.find_all_pdfs(folder)
    if all_pdfs:
        if power_automate.trigger_oc_contacts_flow(folder):
            data.update(excel_sync.lookup_oc_contacts(folder))
        else:
            print(f"WARN: OC contacts flow failed for {folder}")

    # Shipping date — same pattern via the Shipping Date flow + workbook.
    shipping_pdfs = extract_order_pdf.find_shipping_pdfs(folder)
    if shipping_pdfs:
        flow_triggered = power_automate.trigger_shipping_date_flow(data["dossier_no"], folder)
        if not flow_triggered:
            print(f"WARN: shipping date flow failed for {folder}")

        # Read the workbook regardless of whether the flow trigger itself
        # succeeded. After HTTP 200, fall back to the latest row because the
        # current flow writes the generic shipping-subfolder name instead of
        # the parent order folder into Folder_Name for no-date results.
        shipping = excel_sync.lookup_shipping_date(folder)
        if flow_triggered and not shipping:
            shipping = excel_sync.lookup_latest_shipping_result()
        data["shipping_date_reason"] = shipping.get("reasoning")
        if shipping.get("shipping_date"):
            data["shipping_date"] = shipping["shipping_date"]
            print(
                f"Shipping date FOUND for {folder}: {shipping['shipping_date']} "
                f"(source: {shipping.get('source_document')}) — reasoning: {shipping.get('reasoning')}"
            )
        else:
            reasons = []
            if not flow_triggered:
                reasons.append("the shipping-date flow failed to run")
            if shipping.get("reasoning"):
                reasons.append(f"reason: {shipping['reasoning']}")
            warning = f"No shipping date found for {folder}"
            if reasons:
                warning += " — " + "; ".join(reasons)
            data["shipping_date_warning"] = warning
            print(warning)

    data["source_folder"] = folder
    if "cancelled" in os.path.basename(folder).lower():
        data["cancelled"] = "1"

    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        key = data["dossier_no"]
        if merge == "fill_empty":
            storage.fill_empty_fields(conn, key, data, force_fields={"shipping_date_reason"})
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
        {"order": <order dict>, "documents": [<doc dicts>],
         "shipping_date_warning": <str | None>} — the warning is set when a
        shipping-date lookup ran but found no date (states the reason, if any,
        so the UI can surface it to the user).

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

    ingest_result = ingest_folder(folder, db_path=db_path, merge="fill_empty")

    conn = storage.connect(db_path)
    try:
        updated_order = storage.get_order(conn, dossier_no)
        documents = storage.get_documents(conn, dossier_no)
    finally:
        conn.close()

    return {
        "order": updated_order,
        "documents": documents,
        "shipping_date_warning": (ingest_result or {}).get("shipping_date_warning"),
    }


def find_order_folders(root: str) -> list[str]:
    """Every distinct folder under `root` that contains a Checklist*.docx."""
    folders = set()
    for p in glob.glob(os.path.join(root, "**", "Checklist*.docx"), recursive=True):
        if not os.path.basename(p).startswith("~$"):
            folders.add(os.path.dirname(p))
    return sorted(folders)


def _folder_identity(folder: str) -> str:
    """Normalized identity key for an order folder: final folder name only.

    Thin wrapper delegating to `storage.folder_identity()`, the single shared
    implementation (also used by `excel_sync.py` to match Excel rows back to
    a local order folder without needing to import `ingest`).
    """
    return storage.folder_identity(folder)


def scan_new(root: str, db_path: str = storage.DEFAULT_DB) -> dict:
    """Ingest only order folders not yet present in the database.

    Compares on-disk folders against known orders by their final folder name
    (not the full absolute path), since the same shared order folder can be
    synchronized under a different OneDrive root for each user. Folders whose
    name already matches a known order are skipped entirely — no checklist,
    OC, contact, or shipping-date extraction is re-run — but if the matching
    order's stored `source_folder` points to a different absolute path, it is
    rebound to the path found in this scan so Refresh keeps working locally.
    """
    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        known = storage.list_dossier_source_folders(conn)
    finally:
        conn.close()

    # Map normalized folder identity -> (dossier_no, current stored path)
    known_by_identity = {
        _folder_identity(source_folder): (dossier_no, source_folder)
        for dossier_no, source_folder in known
    }

    all_folders = find_order_folders(root)
    new_folders = []
    rebound = []
    for folder in all_folders:
        identity = _folder_identity(folder)
        match = known_by_identity.get(identity)
        if match is None:
            new_folders.append(folder)
            continue
        dossier_no, stored_folder = match
        if os.path.normcase(os.path.normpath(stored_folder)) != os.path.normcase(os.path.normpath(folder)):
            conn = storage.connect(db_path)
            try:
                storage.update_source_folder(conn, dossier_no, folder)
            finally:
                conn.close()
            rebound.append(dossier_no)

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
        "rebound": rebound,
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
