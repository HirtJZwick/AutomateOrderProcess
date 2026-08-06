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

The configured root holds one subfolder per order category (the classic order
folder and the machine order folder). Both `scan_root` and `scan_new` therefore
scan every immediate subfolder of the root in turn, and record the subfolder's
name on each order as `order_group` so the UI can badge and filter by category.
Order folders sitting directly in the root are not ingested.

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

# Shown as the shipping-date hint (the "i" label) when an order has a
# "Shipping Documents and Invoices" folder but nothing inside it looks like a
# shipping document, so the shipping-date flow is never triggered.
NO_MATCHING_SHIPPING_DOCS_REASON = (
    "No shipping date was found although the Shipping documents and Invoices "
    "folder exist for this order"
)

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


def _stored_shipping_date(dossier_no: str, db_path: str) -> str:
    """The shipping date already recorded for `dossier_no`, or "".

    Used to avoid contradicting a date that is already known (typically entered
    by hand) with a "no shipping date was found" hint.
    """
    try:
        conn = storage.connect(db_path)
    except Exception:
        return ""
    try:
        storage.init_db(conn)
        order = storage.get_order(conn, dossier_no)
    except Exception:
        return ""
    finally:
        conn.close()
    return (order or {}).get("shipping_date") or ""


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


def _configured_root() -> str:
    """The configured scan root, or "" when unset or unreadable."""
    try:
        from webapp.backend.settings import load_config

        return (load_config().get("root_folder") or "").strip()
    except Exception:
        return ""


def to_stored_folder(folder: str) -> str:
    """The value to persist in `orders.source_folder` for an on-disk `folder`.

    Order folders live in a shared SharePoint library that every user
    synchronizes to a *different* absolute path (`C:\\Users\\<name>\\OneDrive -
    ...`, or wherever they put the shortcut). Storing the absolute path makes
    the database machine-specific: on any other PC every order reports "no
    valid source_folder on disk" until a full rescan rebinds all of them.

    Folders under the configured scan root are therefore stored *relative* to
    it (`Order_Folders/DO748089 Onboarding Systems OPP396866`), which is
    identical on every machine because it mirrors the SharePoint structure.
    Forward slashes are used, matching `order_documents.rel_path`.

    Anything outside the root — or any path at all while no root is configured
    — is stored unchanged, so nothing is ever lost or silently mangled.
    """
    root = _configured_root()
    if not root or not folder:
        return folder
    try:
        relative = os.path.relpath(os.path.normpath(folder), os.path.normpath(root))
    except ValueError:  # different drives on Windows
        return folder
    parts = relative.split(os.sep)
    if not parts or parts[0] in ("", os.curdir, os.pardir):
        return folder  # not under the root
    return "/".join(parts)


def resolve_source_folder(stored: str) -> str:
    """The absolute on-disk path for a stored `source_folder` value.

    Accepts both forms: a root-relative path (what `to_stored_folder()` now
    writes) is joined onto the configured scan root, while an absolute path —
    written by older versions, or pointing somewhere outside the root — is
    returned unchanged. That fallback is what lets an existing database keep
    working without a migration.
    """
    stored = (stored or "").strip()
    if not stored or os.path.isabs(stored):
        return stored
    root = _configured_root()
    if not root:
        return stored
    return os.path.normpath(os.path.join(root, stored))


def migrate_source_folders_to_relative(db_path: str = storage.DEFAULT_DB) -> int:
    """Rewrite absolute `source_folder` values as root-relative ones.

    Makes an existing database portable in place. Rows already relative, and
    rows pointing outside the configured root, are left untouched. Returns the
    number of rows rewritten.

    Re-running this is harmless, and skipping it entirely is safe too:
    `resolve_source_folder()` still understands absolute values, and the next
    `scan_new()` rebinds whatever it finds.
    """
    if not _configured_root():
        return 0
    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        migrated = 0
        for dossier_no, stored in storage.list_dossier_source_folders(conn):
            if not os.path.isabs(stored):
                continue
            relative = to_stored_folder(stored)
            if relative != stored:
                storage.update_source_folder(conn, dossier_no, relative)
                migrated += 1
        return migrated
    finally:
        conn.close()


def ingest_folder(
    folder: str,
    db_path: str = storage.DEFAULT_DB,
    merge: str = "overwrite",
    order_group: str | None = None,
) -> dict | None:
    """Extract one order from `folder` and write it to the DB.

    Args:
        folder:  Path to the order folder.
        db_path: Path to the SQLite database.
        merge:   "overwrite" (default) — full upsert, replaces all columns.
                 "fill_empty" — only fills columns that are currently empty/NULL
                 in the DB; manually edited values are never clobbered.
                 Documents are always refreshed regardless of merge mode.
        order_group: Name of the root subfolder the order was found in (e.g.
                 "Machine Orders"). Recorded on the order so the UI can badge
                 and filter by category. Pass None (the default) when the group
                 is unknown, leaving any stored value untouched in fill_empty
                 mode.

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
            try:
                data.update(excel_sync.wait_for_oc_contacts(folder))
            except excel_sync.WorkbookUnavailable as exc:
                data["contacts_warning"] = str(exc)
                print(f"WARN: {exc}")
        else:
            print(f"WARN: OC contacts flow failed for {folder}")

    # Shipping date — same pattern via the Shipping Date flow + workbook.
    shipping_pdfs = extract_order_pdf.find_shipping_pdfs(folder)
    if shipping_pdfs:
        # Captured before triggering so a generic row already in the workbook
        # is not mistaken for the one this run produces.
        workbook_mtime = excel_sync.workbook_mtime()
        flow_triggered = power_automate.trigger_shipping_date_flow(data["dossier_no"], folder)
        if not flow_triggered:
            print(f"WARN: shipping date flow failed for {folder}")

        # The flow answers HTTP 200 once it has written to SharePoint, but the
        # local synced copy of the workbook lags behind by a few seconds, so
        # poll rather than read once.
        workbook_error = None
        shipping = {}
        try:
            if flow_triggered:
                shipping = excel_sync.wait_for_shipping_result(folder, workbook_mtime)
            else:
                shipping = excel_sync.lookup_shipping_date(folder)
        except excel_sync.WorkbookUnavailable as exc:
            workbook_error = str(exc)
            print(f"WARN: {exc}")
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
            if workbook_error:
                reasons.append(workbook_error)
            if shipping.get("reasoning"):
                reasons.append(f"reason: {shipping['reasoning']}")
            warning = f"No shipping date found for {folder}"
            if reasons:
                warning += " — " + "; ".join(reasons)
            data["shipping_date_warning"] = warning
            print(warning)
    elif extract_order_pdf.has_shipping_subfolder(folder):
        # Shipping paperwork exists, but no file in it matched
        # `find_shipping_pdfs()` (no "shipping"/"invoice"/"quote" in the name),
        # so the flow is never triggered. Say so via the shipping-date hint
        # instead of leaving the field silently blank.
        if not _stored_shipping_date(data["dossier_no"], db_path):
            data["shipping_date_reason"] = NO_MATCHING_SHIPPING_DOCS_REASON
            print(f"{NO_MATCHING_SHIPPING_DOCS_REASON}: {folder}")

    data["source_folder"] = to_stored_folder(folder)
    if order_group:
        data["order_group"] = order_group
    if "cancelled" in os.path.basename(folder).lower():
        data["cancelled"] = "1"

    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        key = data["dossier_no"]
        if merge == "fill_empty":
            force = {"shipping_date_reason"}
            # A folder moved between root subfolders must re-tag even though
            # the column already holds a (now stale) value.
            if order_group:
                force.add("order_group")
            storage.fill_empty_fields(conn, key, data, force_fields=force)
        else:
            storage.upsert_order(conn, data)
        storage.replace_documents(conn, key, list_documents(folder))
    finally:
        conn.close()
    return data


def _relocate_order_folder(stored_folder: str) -> tuple[str, str] | None:
    """Find `stored_folder` again under the currently configured root.

    The order folders live on a shared SharePoint location synchronized via
    OneDrive, so the local absolute path changes whenever the library is
    re-synced under a different root (e.g. moving from a personal OneDrive to a
    team-site sync root). The stored `source_folder` then points at a path that
    no longer exists, even though the very same order folder is still on disk.

    Matches on the final folder name (the same identity `scan_new` uses), so a
    changed root, or a folder moved between order groups, is resolved.

    Returns (new_folder, group) or None when no match is found.
    """
    identity = _folder_identity(stored_folder)
    if not identity:
        return None
    try:
        from webapp.backend.settings import load_config

        root = (load_config().get("root_folder") or "").strip()
    except Exception:
        return None
    if not root:
        return None
    for group, folder in find_order_folders_by_group(root):
        if _folder_identity(folder) == identity:
            return folder, group
    return None


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
                    and the folder cannot be located under the configured root.
    """
    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        order = storage.get_order(conn, dossier_no)
        if order is None:
            raise ValueError(f"Order {dossier_no!r} not found in database.")
        stored = (order.get("source_folder") or "").strip()
        order_group = None
        if not stored:
            raise ValueError(f"Order {dossier_no!r} has no source_folder recorded.")
        folder = resolve_source_folder(stored)
        if not os.path.isdir(folder):
            relocated = _relocate_order_folder(stored)
            if relocated is None:
                raise ValueError(
                    f"Order {dossier_no!r} has no valid source_folder on disk: "
                    f"{folder!r}. The folder was not found under the configured "
                    f"scan folder either — check the scan folder in Settings, "
                    f"then run 'Scan new orders' to rebind the stored paths."
                )
            folder, order_group = relocated
            storage.update_source_folder(
                conn, dossier_no, to_stored_folder(folder), order_group=order_group
            )
    finally:
        conn.close()

    ingest_result = ingest_folder(
        folder,
        db_path=db_path,
        merge="fill_empty",
        order_group=order_group or _configured_order_group(folder),
    )

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
        "contacts_warning": (ingest_result or {}).get("contacts_warning"),
    }


def find_order_folders(root: str) -> list[str]:
    """Every distinct folder under `root` that contains a Checklist*.docx."""
    folders = set()
    for p in glob.glob(os.path.join(root, "**", "Checklist*.docx"), recursive=True):
        if not os.path.basename(p).startswith("~$"):
            folders.add(os.path.dirname(p))
    return sorted(folders)


def list_order_groups(root: str) -> list[str]:
    """Sorted names of the immediate subfolders of `root` ("order groups").

    The configured root no longer holds order folders directly: it contains one
    subfolder per order category (the classic order folder and the machine
    order folder). Each of those is scanned in turn. Enumerating them instead
    of hard-coding their names means renaming a folder, or adding a third one,
    keeps working without a code change.

    Hidden folders and Office lock artifacts ("~$...") are skipped.
    """
    if not os.path.isdir(root):
        return []
    groups = [
        name
        for name in os.listdir(root)
        if os.path.isdir(os.path.join(root, name))
        and not name.startswith((".", "~$"))
    ]
    return sorted(groups, key=os.path.normcase)


def find_order_folders_by_group(root: str) -> list[tuple[str, str]]:
    """(group, order_folder) pairs for every order folder inside a subfolder.

    Each immediate subfolder of `root` is searched in turn (in the deterministic
    order given by `list_order_groups`), so the classic order folder is fully
    scanned before the machine order folder. Order folders sitting directly in
    `root` are intentionally NOT returned — only orders filed under one of the
    category subfolders count, so a subfolder that is itself an order folder
    (its own `Checklist*.docx` at the top level) is skipped.

    The categories can overlap on disk: the SharePoint library exposes the
    machine order folder both as its own top-level shortcut *and* nested inside
    the classic order folder. An order reached through another category's folder
    therefore belongs to that other category, not to the one being walked, and
    is skipped here so it is counted (and tagged) exactly once.
    """
    groups = list_order_groups(root)
    group_names = {os.path.normcase(name) for name in groups}
    pairs = []
    seen = set()
    for group in groups:
        group_path = os.path.join(root, group)
        group_key = os.path.normcase(os.path.normpath(group_path))
        this_group = os.path.normcase(group)
        for folder in find_order_folders(group_path):
            normalized = os.path.normcase(os.path.normpath(folder))
            if normalized == group_key:
                continue  # an order folder sitting directly in the root
            if _under_other_group(folder, group_path, group_names, this_group):
                continue  # reached through a different category's folder
            identity = _folder_identity(folder)
            if identity in seen:
                continue  # already found under an earlier category
            seen.add(identity)
            pairs.append((group, folder))
    return pairs


def _under_other_group(
    folder: str, group_path: str, group_names: set[str], this_group: str
) -> bool:
    """True when `folder` sits inside a directory named after another group.

    Walking `Order_Folders` reaches `Order_Folders/New_Machines_Order_Folder/...`,
    which really belongs to the machine category. Directories matching the
    group currently being walked are not treated as foreign, so the library's
    own `New_Machines_Order_Folder/New_Machines_Order_Folder/...` nesting stays
    within its category.
    """
    try:
        relative = os.path.relpath(os.path.normpath(folder), os.path.normpath(group_path))
    except ValueError:  # different drives on Windows
        return False
    parts = [os.path.normcase(p) for p in relative.split(os.sep)[:-1]]
    return any(part in group_names and part != this_group for part in parts)


def order_group_for_folder(root: str, folder: str) -> str | None:
    """The root subfolder `folder` lives under, or None if it is not under `root`.

    Used by `refresh_order` to re-derive an order's group from its stored
    `source_folder` without re-walking the whole tree.
    """
    if not root or not folder:
        return None
    try:
        relative = os.path.relpath(os.path.normpath(folder), os.path.normpath(root))
    except ValueError:  # different drives on Windows
        return None
    parts = relative.split(os.sep)
    if not parts or parts[0] in ("", os.curdir, os.pardir):
        return None
    return parts[0]


def _configured_order_group(folder: str) -> str | None:
    """`order_group_for_folder()` against the configured root_folder.

    Returns None when no root is configured, config cannot be read, or the
    folder is not under the root — in which case the caller leaves the stored
    group untouched rather than clearing it.
    """
    try:
        from webapp.backend.settings import load_config

        root = (load_config().get("root_folder") or "").strip()
    except Exception:
        return None
    if not root:
        return None
    return order_group_for_folder(root, folder)


def _folder_identity(folder: str) -> str:
    """Normalized identity key for an order folder: final folder name only.

    Thin wrapper delegating to `storage.folder_identity()`, the single shared
    implementation (also used by `excel_sync.py` to match Excel rows back to
    a local order folder without needing to import `ingest`).
    """
    return storage.folder_identity(folder)


def scan_new(root: str, db_path: str = storage.DEFAULT_DB) -> dict:
    """Ingest only order folders not yet present in the database.

    Every immediate subfolder of `root` (the classic order folder, the machine
    order folder, ...) is scanned in turn — see `find_order_folders_by_group()`.

    Compares on-disk folders against known orders by their final folder name
    (not the full absolute path), since the same shared order folder can be
    synchronized under a different OneDrive root for each user. Folders whose
    name already matches a known order are skipped entirely — no checklist,
    OC, contact, or shipping-date extraction is re-run — but if the matching
    order's stored `source_folder` points to a different absolute path, or its
    stored `order_group` no longer matches the subfolder it was found in, those
    are rebound to what this scan found so Refresh keeps working locally and the
    category stays accurate.
    """
    conn = storage.connect(db_path)
    try:
        storage.init_db(conn)
        known = storage.list_dossier_source_folders(conn)
        known_groups = {
            dossier_no: storage.get_order_group(conn, dossier_no)
            for dossier_no, _ in known
        }
    finally:
        conn.close()

    # Map normalized folder identity -> (dossier_no, current stored path)
    known_by_identity = {
        _folder_identity(source_folder): (dossier_no, source_folder)
        for dossier_no, source_folder in known
    }

    group_folders = find_order_folders_by_group(root)
    new_folders = []
    rebound = []
    for group, folder in group_folders:
        identity = _folder_identity(folder)
        match = known_by_identity.get(identity)
        if match is None:
            new_folders.append((group, folder))
            continue
        dossier_no, stored_folder = match
        new_stored = to_stored_folder(folder)
        path_changed = os.path.normcase(os.path.normpath(stored_folder)) != os.path.normcase(
            os.path.normpath(new_stored)
        )
        group_changed = (known_groups.get(dossier_no) or "") != group
        if path_changed or group_changed:
            conn = storage.connect(db_path)
            try:
                storage.update_source_folder(conn, dossier_no, new_stored, order_group=group)
            finally:
                conn.close()
            rebound.append(dossier_no)

    ingested, skipped = [], []
    aborted = None
    for group, folder in new_folders:
        try:
            order = ingest_folder(folder, db_path=db_path, order_group=group)
            if order:
                ingested.append(order.get("dossier_no"))
            else:
                skipped.append(folder)
        except Exception as exc:
            aborted = str(exc)
            break  # stop — no requests left
    result = {
        "root": root,
        "groups": sorted({group for group, _ in group_folders}, key=os.path.normcase),
        "folders_found": len(group_folders),
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
    """Ingest every order folder under `root`. Returns a summary dict.

    Each immediate subfolder of `root` (classic orders, machine orders, ...) is
    scanned in turn; order folders sitting directly in `root` are ignored.
    """
    group_folders = find_order_folders_by_group(root)
    ingested, skipped = [], []
    aborted = None
    for group, folder in group_folders:
        try:
            order = ingest_folder(folder, db_path=db_path, order_group=group)
            if order:
                ingested.append(order.get("dossier_no"))
            else:
                skipped.append(folder)
        except Exception as exc:
            aborted = str(exc)
            break  # stop — no requests left
    result = {
        "root": root,
        "groups": sorted({group for group, _ in group_folders}, key=os.path.normcase),
        "folders_found": len(group_folders),
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
