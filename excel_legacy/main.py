"""
main.py
-------
Orchestrator for the Eric Checklist -> FAT Plan automation.

Pipeline:  Checklist*.docx  ->  extract  ->  SQLite (eric_orders.db)  ->  FAT_INSTALL*.xlsx

Invoked by Power Automate Desktop via run_python.ps1, e.g.:
    run_python.ps1 -ScriptPath .\\main.py -ScriptArgs "C:\\OneDrive\\...\\Checklist ....docx"

Arguments:
    [1] (optional) path to the Checklist .docx. If omitted, the newest
        Checklist*.docx in this folder is used.

Exit codes: 0 ok | 4 docx missing | 7 no dossier key extracted
"""
from __future__ import annotations

import os
import sys

# Core extraction modules live in the parent directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extract_checklist
import extract_order_pdf
import storage
import update_fat_plan


def run(docx_path: str | None = None) -> int:
    folder = os.path.dirname(os.path.abspath(__file__))

    path = docx_path or extract_checklist.find_checklist(folder)
    if not path or not os.path.exists(path):
        print(f"ERROR: checklist file not found: {path}", file=sys.stderr)
        return 4

    print(f"[1/3] Extracting: {os.path.basename(path)}")
    data = extract_checklist.extract(path)
    if not data.get("dossier_no"):
        print("ERROR: could not extract a Dossier No. (order key).", file=sys.stderr)
        return 7
    print(f"      Extracted {len(data)} fields for dossier {data['dossier_no']}.")

    # Enrich with the Order Confirmation PDF (ZwickRoell contacts: RSM, Logistics).
    src_dir = os.path.dirname(os.path.abspath(path))
    order_pdf = extract_order_pdf.find_order_pdf(src_dir)
    if order_pdf:
        pdf_data = extract_order_pdf.extract(order_pdf)
        data.update(pdf_data)
        print(f"      Merged {len(pdf_data)} fields from {os.path.basename(order_pdf)}.")
    else:
        print("      No 'Order' PDF found to enrich contacts (skipping).")

    print("[2/3] Staging to SQLite (eric_orders.db)")
    key = storage.store(data)
    print(f"      Upserted order {key}.")

    print("[3/3] Writing FAT_INSTALL workbook")
    conn = storage.connect()
    order = storage.get_order(conn, key)
    conn.close()
    xlsx = update_fat_plan.find_workbook(folder)
    if not xlsx:
        print("ERROR: FAT_INSTALL*.xlsx not found.", file=sys.stderr)
        return 6
    changes = update_fat_plan.write_plan(order, xlsx, evidence_dir=src_dir)
    print(f"      {len(changes)} cells updated in {os.path.basename(xlsx)}.")
    for c in changes:
        print("        " + c)

    print("Done.")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(run(arg))
