from webapp.backend.derive import derive_stage, derive_completeness


# ── Stage tests ───────────────────────────────────────────────────────────────

def test_new_order_has_no_dates():
    assert derive_stage({})["name"] == "New"


def test_order_confirmed_stage():
    assert derive_stage({"received_oc_from_zrx": "2/1/2026"})["name"] == "Order Confirmed"


def test_packed_when_packing_details_set():
    assert derive_stage({"packing_details_from_zrx": "1/1/2026"})["name"] == "Packed"


def test_shipped_when_shipping_date_set():
    assert derive_stage({"shipping_date": "5/15/2026"})["name"] == "Shipped"


def test_shipped_takes_precedence_over_packed():
    order = {"shipping_date": "5/15/2026", "packing_details_from_zrx": "5/10/2026"}
    assert derive_stage(order)["name"] == "Shipped"


def test_stage_indices_are_ordered():
    new_idx = derive_stage({})["index"]
    confirmed_idx = derive_stage({"received_oc_from_zrx": "x"})["index"]
    packed_idx = derive_stage({"packing_details_from_zrx": "x"})["index"]
    shipped_idx = derive_stage({"shipping_date": "x"})["index"]
    assert new_idx < confirmed_idx < packed_idx < shipped_idx


def test_stage_includes_all_stages():
    assert derive_stage({})["stages"] == ["New", "Order Confirmed", "Packed", "Shipped"]


# ── Completeness tests ────────────────────────────────────────────────────────

def test_completeness_empty_order():
    assert derive_completeness({})["percent"] == 0


def test_completeness_full_order():
    order = {
        "customer_name": "Charlie",
        "ship_to_address": "123 Main St",
        "dossier_no": "D12345",
        "order_id": "O12345",
        "machine_type": "Z010",
        "industry": "Manufacturing",
        "order_date": "05/15/2026",
        "received_oc_from_zrx": "02/15/2026",
        "oc_sent_to_customer": "02/16/2026",
        "rsm": "John Doe",
        "logistics_coordinator": "Jane Smith",
    }
    result = derive_completeness(order)
    assert result["percent"] == 100
    assert result["level"] == "full"


def test_completeness_partial_order():
    order = {"customer_name": "Alice", "dossier_no": "D001", "machine_type": "Z010"}
    result = derive_completeness(order)
    assert 0 < result["percent"] < 100


def test_completeness_no_checklist_gives_missing_level():
    assert derive_completeness({}, has_checklist=False)["level"] == "missing"


def test_completeness_counts_present_fields():
    order = {"customer_name": "Alice", "dossier_no": "D001"}
    result = derive_completeness(order)
    assert result["present"] == 2
    assert result["total"] == 11