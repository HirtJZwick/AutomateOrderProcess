"""
derive.py
---------
Presentation-only derivations for the dashboard. These read directly from the
stored order fields - they intentionally do NOT use the milestone rule engine.

- `stage`: a simple high-level order stage from the key dates.
- `completeness`: how much of the expected information we have.
"""
from __future__ import annotations

# High-level stage band (order matters: later stages take precedence).
STAGES = ["New", "Order Confirmed", "Packed", "Shipped"]

# Fields that signal each stage has been reached.
_SHIPPED_FIELDS = ["shipping_date"]
_PACKED_FIELDS = ["packing_details_from_zrx"]
_CONFIRMED_FIELDS = ["received_oc_from_zrx", "oc_sent_to_customer"]

# Fields used to score how complete an order's extracted information is.
_EXPECTED_FIELDS = [
    "customer_name",
    "ship_to_address",
    "dossier_no",
    "order_id",
    "machine_type",
    "industry",
    "order_date",
    "received_oc_from_zrx",
    "oc_sent_to_customer",
    "rsm",
    "logistics_coordinator",
]


def _has(order: dict, key: str) -> bool:
    return bool((order.get(key) or "").strip())


def derive_stage(order: dict) -> dict:
    """Return {name, index} for the current high-level stage."""
    if any(_has(order, f) for f in _SHIPPED_FIELDS):
        name = "Shipped"
    elif any(_has(order, f) for f in _PACKED_FIELDS):
        name = "Packed"
    elif any(_has(order, f) for f in _CONFIRMED_FIELDS):
        name = "Order Confirmed"
    else:
        name = "New"
    return {"name": name, "index": STAGES.index(name), "stages": STAGES}


def derive_completeness(order: dict, has_checklist: bool = True) -> dict:
    """Return {percent, present, total, level} for the info-completeness bar."""
    present = sum(1 for f in _EXPECTED_FIELDS if _has(order, f))
    total = len(_EXPECTED_FIELDS)
    percent = round(100 * present / total) if total else 0

    if not has_checklist:
        level = "missing"
    elif percent >= 80:
        level = "full"
    elif percent >= 40:
        level = "partial"
    else:
        level = "low"
    return {"percent": percent, "present": present, "total": total, "level": level}


def derive_active(order: dict) -> bool:
    """True when the order has an OC date but no shipping date and is not cancelled.

    These are confirmed, in-flight orders that Eric is actively managing before
    the machine reaches the customer.
    """
    return (
        _has(order, "received_oc_from_zrx")
        and not _has(order, "shipping_date")
        and order.get("cancelled") != "1"
    )
