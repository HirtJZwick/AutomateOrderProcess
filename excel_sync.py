"""
excel_sync.py
-------------
Reads contact and shipping-date data that a Power Automate flow has written to
two shared Excel workbooks, keyed by order folder name, and matches rows back
to a local order folder via `storage.folder_identity()`.

This module replaces `llm_extract_phi.py` / `llm_extract.py`: order-confirmation
contacts (logistics coordinator + RSM) and the shipping date are no longer
derived by an LLM reading PDFs directly. Instead:

  1. `ingest.py` triggers a Power Automate flow (see `power_automate.py`) for
     the order's folder.
  2. The flow reads the order's documents itself (via its own SharePoint/
     OneDrive connectors) and appends/updates a row in one of these workbooks.
  3. Once the flow's HTTP trigger responds (synchronously, HTTP 200), this
     module reads the workbook and looks up the row matching the folder that
     was just processed.

File locations are currently hard-coded to the shared OneDrive folder Eric and
Anita use; update the two path constants below if that location changes.
"""
from __future__ import annotations

import os

import openpyxl

import storage

# Update this if the shared workbook location changes.
_ERIC_PROJECT_ROOT = (
    r"C:\Users\Hirtj\OneDrive - ZwickRoell GmbH & Co. KG\Documents\EricProject"
)
OC_CONTACTS_PATH = os.path.join(_ERIC_PROJECT_ROOT, "OC_Contacts.xlsx")
SHIPPING_DATE_PATH = os.path.join(_ERIC_PROJECT_ROOT, "Dossier_Shipping_Date.xlsx")

# OC_Contacts.xlsx column -> orders table column.
_OC_CONTACT_COLUMNS = {
    "Logistics_Coordinator": "logistics_coordinator",
    "Logistics_Coordinator_Email": "logistics_coordinator_email",
    "RSM": "rsm",
    "RSM_Email": "rsm_email",
}


def _read_rows(path: str) -> list[dict]:
    """Read all data rows of the first sheet as header->value dicts.

    Tolerant of blank leading rows/columns (as produced by the flow) — finds
    the header row by locating "Folder_Name" in the first column. Returns []
    if the file doesn't exist yet or has no recognizable header.
    """
    if not os.path.exists(path):
        return []
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header_idx = next(
        (i for i, row in enumerate(rows) if row and row[0] == "Folder_Name"), None
    )
    if header_idx is None:
        return []
    headers = rows[header_idx]
    out = []
    for row in rows[header_idx + 1:]:
        if not row or not row[0]:
            continue
        out.append({headers[i]: row[i] for i in range(len(headers)) if i < len(row)})
    return out


def _matching_rows(rows: list[dict], folder: str) -> list[dict]:
    identity = storage.folder_identity(folder)
    return [
        row for row in rows
        if storage.folder_identity(str(row.get("Folder_Name") or "")) == identity
    ]


def _format_date(value) -> str | None:
    """Format a Shipping_Date cell as 'M/D/YYYY' (matches storage._parse_order_date)."""
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return f"{value.month}/{value.day}/{value.year}"
    text = str(value).strip()
    return text or None


def lookup_oc_contacts(folder: str, path: str = OC_CONTACTS_PATH) -> dict:
    """Return the contact fields for `folder`'s matching row, or {} if absent.

    If multiple rows match (the flow may append duplicates on repeated runs),
    the LAST matching row wins (most recent).
    """
    matches = _matching_rows(_read_rows(path), folder)
    if not matches:
        return {}
    match = matches[-1]
    result = {}
    for col, field in _OC_CONTACT_COLUMNS.items():
        value = match.get(col)
        if value not in (None, ""):
            result[field] = str(value).strip()
    return result


def lookup_shipping_date(folder: str, path: str = SHIPPING_DATE_PATH) -> dict:
    """Return {"shipping_date", "reasoning", "source_document"} for `folder`'s
    matching row, or {} if no row matches or the row has neither a date nor a
    reason to report.

    `shipping_date` may be None while `reasoning` is still populated — this
    happens when the flow couldn't determine a date but recorded why (e.g. no
    shipping documents were found yet). Callers use the reasoning in that case
    to explain to the user why no shipping date is available.
    """
    matches = _matching_rows(_read_rows(path), folder)
    if not matches:
        return {}
    match = matches[-1]
    shipping_date = _format_date(match.get("Shipping_Date"))
    reasoning = match.get("Reason")
    source_document = match.get("Document")
    if not shipping_date and not reasoning:
        return {}
    return {
        "shipping_date": shipping_date,
        "reasoning": reasoning,
        "source_document": source_document,
    }


def lookup_latest_shipping_result(path: str = SHIPPING_DATE_PATH) -> dict:
    """Return the latest usable result written by the shipping-date flow.

    The current flow writes "Shipping Documents and Invoices" into Folder_Name
    for no-date results and may update/reuse that generic row instead of always
    appending a new row. Immediately after the synchronous flow returns HTTP
    200, the latest usable workbook row is therefore the only available key for
    retrieving that result when the normal order-folder lookup fails.
    """
    for row in reversed(_read_rows(path)):
        shipping_date = _format_date(row.get("Shipping_Date"))
        reasoning = row.get("Reason")
        if shipping_date or reasoning:
            return {
                "shipping_date": shipping_date,
                "reasoning": reasoning,
                "source_document": row.get("Document"),
            }
    return {}
