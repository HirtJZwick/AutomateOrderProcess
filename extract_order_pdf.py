"""
extract_order_pdf.py
--------------------
Header parsing + PDF discovery for an order folder.

The internal ZwickRoell contacts (logistics coordinator, RSM) used to be parsed
with brittle regex here; that job now belongs to `llm_extract.extract_order_contacts`
because the Order PDFs are not consistently structured. This module keeps the
parts that are still regular and cheap:

  - parse_header(): cross-reference numbers from the OC header (PO no, quotation no)
  - find_order_pdf(): locate the Order PDF in a folder
  - find_shipping_pdfs(): locate shipping PDFs in the
    "Shipping Documents and Invoices" subfolder

Usage:
    python extract_order_pdf.py "C:\\path\\to\\DO737348 Order Confirmation.pdf"
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

import pdfplumber

SHIPPING_SUBFOLDER = "Shipping Documents and Invoices"


def read_text(pdf_path: str, max_pages: int = 2) -> str:
    """Return the concatenated text of the first `max_pages` pages."""
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:max_pages]:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def parse_header(text: str) -> dict:
    """Pull cross-reference identifiers from the OC header."""
    out = {}
    patterns = {
        "oc_purchase_order_no": r"Purchase order no\.?:?\s*(\S+)",
        "oc_quotation_no": r"quotation no\.?:?\s*(\S+)",
        "oc_dossier_no": r"dossier no\.?:?\s*(\S+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.I)
        if m:
            out[key] = m.group(1).strip()
    return out


def extract(pdf_path: str) -> dict:
    """Header-only extraction from the Order PDF (contacts come from the LLM)."""
    text = read_text(pdf_path)
    data: dict = {"oc_source_file": os.path.basename(pdf_path)}
    data.update(parse_header(text))
    return {k: v for k, v in data.items() if v}


def find_order_pdf(folder: str) -> str | None:
    """Return an 'Order' PDF in `folder` (filename contains 'Order').

    Prefers an Order Confirmation when several candidates exist.
    """
    hits = [
        p
        for p in glob.glob(os.path.join(folder, "*.pdf"))
        if "order" in os.path.basename(p).lower()
        and not os.path.basename(p).startswith("~$")
        and "backup" not in os.path.basename(p).lower()
    ]
    if not hits:
        return None
    hits.sort(key=lambda p: (0 if "confirmation" in os.path.basename(p).lower() else 1,
                             os.path.basename(p).lower()))
    return hits[0]


def find_shipping_pdfs(folder: str) -> list[str]:
    """Return delivery PDFs inside the 'Shipping Documents and Invoices' subfolder.

    Only PDFs whose filename contains 'delivery' (case-insensitive) are returned.
    Returns an empty list if that subfolder does not exist.
    """
    shipping_dir = os.path.join(folder, SHIPPING_SUBFOLDER)
    if not os.path.isdir(shipping_dir):
        return []
    hits = [
        p
        for p in glob.glob(os.path.join(shipping_dir, "**", "*.pdf"), recursive=True)
        if "delivery" in os.path.basename(p).lower()
        and not os.path.basename(p).startswith("~$")
    ]
    return sorted(hits)


def main(argv):
    path = argv[1] if len(argv) > 1 else find_order_pdf(os.path.dirname(os.path.abspath(__file__)))
    if not path or not os.path.exists(path):
        print(f"ERROR: order PDF not found: {path}", file=sys.stderr)
        return 4
    print(json.dumps(extract(path), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
