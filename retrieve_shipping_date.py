"""
retrieve_shipping_date.py
-------------------------
Scan a root directory for order folders, extract the shipping_date from delivery
PDFs found in each folder's "Shipping Documents and Invoices" subfolder via the
LLM, and write one result JSON per folder into `shipping_date_results/`.

Folders that already have a result file with a shipping_date are skipped
("retrieve once" behaviour).  If the API rate limit is hit, progress is saved
and a pop-up notifies you — re-run without arguments to resume.

Usage
-----
  # First run — provide the root orders directory:
  python retrieve_shipping_date.py "C:\\path\\to\\orders\\root"

  # Resume after a rate-limit pause (reads saved state automatically):
  python retrieve_shipping_date.py
"""
from __future__ import annotations

import json
import os
import sys
import tkinter
from tkinter import messagebox

from openai import RateLimitError

import extract_order_pdf
import llm_extract

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATE_FILE = os.path.join(_HERE, "retrieve_shipping_date_state.json")
_RESULTS_DIR = os.path.join(_HERE, "shipping_date_results")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _show_popup(title: str, message: str) -> None:
    """Display a modal Windows message-box."""
    root = tkinter.Tk()
    root.withdraw()
    messagebox.showwarning(title, message)
    root.destroy()


def _safe_filename(name: str) -> str:
    """Replace characters that are illegal in Windows file names."""
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name


def _result_path(folder: str) -> str:
    folder_name = os.path.basename(os.path.normpath(folder))
    return os.path.join(_RESULTS_DIR, f"{_safe_filename(folder_name)}.json")


def _already_done(folder: str) -> bool:
    """Return True if a result JSON already exists and contains a shipping_date."""
    p = _result_path(folder)
    if not os.path.exists(p):
        return False
    try:
        return bool(json.loads(open(p, encoding="utf-8").read()).get("shipping_date"))
    except Exception:
        return False


def _write_result(folder: str, result: dict) -> None:
    os.makedirs(_RESULTS_DIR, exist_ok=True)
    with open(_result_path(folder), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


def _load_state() -> dict | None:
    if os.path.exists(_STATE_FILE):
        try:
            return json.loads(open(_STATE_FILE, encoding="utf-8").read())
        except Exception:
            pass
    return None


def _save_state(root: str, index: int) -> None:
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"root": root, "current_index": index}, f, indent=2)


def _clear_state() -> None:
    if os.path.exists(_STATE_FILE):
        os.remove(_STATE_FILE)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def get_pdf_files(root: str, start_index: int = 0) -> None:
    """Walk `root`, find delivery PDFs in each subfolder, query LLM for shipping_date.

    Writes one JSON result file per folder.  Skips folders already processed.
    On rate-limit, saves progress and shows a popup before exiting.
    """
    folders = sorted(
        os.path.join(root, d)
        for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d))
    )
    total = len(folders)
    print(f"Found {total} folder(s) in '{root}'. Starting at index {start_index}.")

    for i, folder in enumerate(folders):
        if i < start_index:
            continue

        name = os.path.basename(folder)

        if _already_done(folder):
            print(f"[{i + 1}/{total}] SKIP (already done): {name}")
            continue

        shipping_pdfs = extract_order_pdf.find_shipping_pdfs(folder)
        if not shipping_pdfs:
            print(f"[{i + 1}/{total}] SKIP (no delivery PDFs): {name}")
            continue

        print(f"[{i + 1}/{total}] Processing: {name}  ({len(shipping_pdfs)} PDF(s))")

        shipping_date = None
        source_file = None

        for pdf_path in shipping_pdfs:
            try:
                result = llm_extract.extract_shipping_date(pdf_path)
            except RateLimitError as exc:
                _save_state(root, i)
                msg = (
                    f"Rate limit reached at folder {i + 1}/{total}:\n"
                    f"  {name}\n\n"
                    f"Progress has been saved.\n"
                    f"Re-run the script without arguments to resume from here."
                )
                print(f"RATE LIMIT: {exc}")
                _show_popup("Rate Limit Reached — Shipping Date Extraction", msg)
                sys.exit(1)
            except Exception as exc:
                print(f"  WARN: {os.path.basename(pdf_path)}: {exc}")
                continue

            if result.get("shipping_date"):
                shipping_date = result["shipping_date"]
                source_file = os.path.basename(pdf_path)
                break  # found — no need to check remaining PDFs in this folder

        _write_result(folder, {"shipping_date": shipping_date, "source": source_file})
        if shipping_date:
            print(f"  -> shipping_date: {shipping_date}  (from {source_file})")
        else:
            print(f"  -> shipping_date: not found")

    _clear_state()
    print(f"\nDone. Results written to: {_RESULTS_DIR}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    state = _load_state()

    if len(argv) > 1:
        root = argv[1]
        start_index = 0
        if state and state.get("root") == root:
            ans = input(
                f"Saved state found at index {state['current_index']}. Resume? [y/N] "
            ).strip().lower()
            if ans == "y":
                start_index = state["current_index"]
    elif state:
        root = state["root"]
        start_index = state["current_index"]
        print(f"Resuming from folder index {start_index} in: {root}")
    else:
        print("Usage: python retrieve_shipping_date.py <root_folder>")
        return 1

    if not os.path.isdir(root):
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 2

    get_pdf_files(root, start_index=start_index)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
