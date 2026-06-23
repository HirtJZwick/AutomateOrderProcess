"""
milestone_status.py
--------------------
Infer MILESTONE TRACKING statuses (FAT Plan rows 24-35) the way Eric does it:
look at which documents have arrived in the order folder and which dates the
checklist records, then mark the corresponding milestone as Completed / In
Progress with its Actual Date and a short evidence note.

Design rules (agreed):
  * Only ever change a row whose Status is empty or "Not Started" - never
    overwrite a status Eric set by hand.
  * Rows that do not apply to the order (e.g. FAT / Installation / IQOQ for a
    spare-part order) are left untouched - no rule emits them here.
  * Each updated row gets Status (col F), Actual Date (col C) and a short note
    (col H).

`infer_statuses` returns: {row_number: {"status", "date", "note"}}.
"""
from __future__ import annotations

import glob
import os
import re

# Status vocabulary from the sheet's legend.
COMPLETED = "Completed"
IN_PROGRESS = "In Progress"

_DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")


def _first_date(*values: str | None) -> str | None:
    """Return the first MM/DD/YYYY-style date found in any of the values."""
    for v in values:
        if not v:
            continue
        m = _DATE_RE.search(str(v))
        if m:
            return m.group(1)
    return None


# --------------------------------------------------------------------------- #
# Evidence: what documents are present in the order folder (incl. subfolders)
# --------------------------------------------------------------------------- #
def scan_evidence(folder: str, order: dict | None = None) -> dict:
    """Inspect `folder` for the documents Eric relies on. Returns booleans."""
    order = order or {}
    names = []
    for p in glob.glob(os.path.join(folder, "**", "*"), recursive=True):
        if os.path.isfile(p):
            names.append(os.path.basename(p).lower())

    def has(*subs: str) -> bool:
        return any(all(s in n for s in subs) for n in names)

    po_no = (order.get("oc_purchase_order_no") or order.get("purchase_order_no") or "").lower()

    return {
        "order_confirmation": has("order", "confirmation"),
        "zru_oc": has("zru", "oc") or has("zru", "order"),
        "purchase_order": bool(po_no and any(po_no in n for n in names)),
        "invoice": has("invoice"),
        "shipping": any("shipping" in n for n in names) or has("invoice"),
        "fat_report": has("fat", "report"),
        "installation_report": has("installation", "report"),
        "iqoq_protocol": has("iqoq") or has("iq", "oq"),
    }


# --------------------------------------------------------------------------- #
# Inference
# --------------------------------------------------------------------------- #
def infer_statuses(order: dict, evidence: dict) -> dict:
    """Map evidence + extracted dates to milestone rows. Conservative: only emit
    a row when there is solid evidence the milestone has happened."""
    out: dict[int, dict] = {}

    def mark(row, status, date, note):
        out[row] = {"status": status, "date": date, "note": note}

    # Row 24 - Confirm order from ZRU to ZNRA.
    oc_date = _first_date(order.get("received_oc_from_zrx"))
    if oc_date or evidence.get("zru_oc") or evidence.get("order_confirmation"):
        note = (
            f"OC received from ZRX {oc_date}" if oc_date
            else "ZRU order confirmation document present"
        )
        mark(24, COMPLETED, oc_date, note)

    # Row 31 - Shipment of system.
    ship_date = _first_date(
        order.get("collection_order_to_forwarder"),
        order.get("information_customer_cia"),
        order.get("invoice_received_from_zrx"),
        order.get("packing_details_from_zrx"),
    )
    tracking = _tracking_number(order.get("collection_order_to_forwarder"))
    shipped = bool(
        tracking
        or evidence.get("invoice")
        or _first_date(order.get("invoice_received_from_zrx"))
    )
    if shipped:
        bits = []
        if tracking:
            bits.append(f"tracking {tracking}")
        if evidence.get("invoice"):
            bits.append("invoice on file")
        note = "Shipped" + (" (" + ", ".join(bits) + ")" if bits else "")
        mark(31, COMPLETED, ship_date, note)
    elif _first_date(order.get("packing_details_from_zrx")):
        mark(31, IN_PROGRESS, _first_date(order.get("packing_details_from_zrx")),
             "Packing details received from ZRX")

    return out


def _tracking_number(raw: str | None) -> str | None:
    """Pull a carrier tracking number (e.g. 'UPS 1ZV357A50442428615')."""
    if not raw:
        return None
    m = re.search(r"\b(1Z[0-9A-Z]{16})\b", raw)
    if m:
        return m.group(1)
    # Fallback: a long alphanumeric token that is not purely a date.
    m = re.search(r"\b([0-9A-Z]{10,})\b", raw)
    return m.group(1) if m else None
