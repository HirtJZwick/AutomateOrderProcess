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


def find_all_pdfs(folder: str) -> list[str]:
    """Return all PDF files in `folder` root (non-recursive) whose filename
    contains "oc" or "order" (case-insensitive).

    Excludes temp files (~$...) and files with 'backup' in their name.
    Sorted so Order Confirmation files come first, then alphabetically.
    """
    hits = [
        p
        for p in glob.glob(os.path.join(folder, "*.pdf"))
        if not os.path.basename(p).startswith("~$")
        and "backup" not in os.path.basename(p).lower()
        and ("oc" in os.path.basename(p).lower() or "order" in os.path.basename(p).lower())
    ]
    hits.sort(key=lambda p: (0 if "confirmation" in os.path.basename(p).lower() else 1,
                             os.path.basename(p).lower()))
    return hits


def find_order_pdf(folder: str) -> str | None:
    """Return the best single Order PDF in `folder`, or None if not found."""
    hits = find_all_pdfs(folder)
    return hits[0] if hits else None



_SHIPPING_FILENAME_KEYWORDS = ("shipping", "invoice", "quote")


def find_shipping_pdfs(folder: str) -> list[str]:
    """Return shipping-related PDFs inside the 'Shipping Documents and Invoices'
    subfolder.

    Only searches within that subfolder — never the rest of the order folder.
    Returns an empty list if the subfolder does not exist. Of the PDFs found,
    only those whose filename contains "shipping", "invoice", or "quote"
    (case-insensitive) are returned.
    """
    shipping_dir = os.path.join(folder, SHIPPING_SUBFOLDER)
    if not os.path.isdir(shipping_dir):
        return []
    hits = [
        p
        for p in glob.glob(os.path.join(shipping_dir, "**", "*.pdf"), recursive=True)
        if any(kw in os.path.basename(p).lower() for kw in _SHIPPING_FILENAME_KEYWORDS)
        and not os.path.basename(p).startswith("~$")
    ]
    return sorted(hits)


def has_shipping_subfolder(folder: str) -> bool:
    """True when the order has a 'Shipping Documents and Invoices' subfolder.

    Lets the caller distinguish "this order has no shipping paperwork at all"
    from "shipping paperwork exists but nothing in it matched
    `find_shipping_pdfs()`" — the latter is worth telling the user about.
    """
    return os.path.isdir(os.path.join(folder, SHIPPING_SUBFOLDER))


def main(argv):
    path = argv[1] if len(argv) > 1 else find_order_pdf(os.path.dirname(os.path.abspath(__file__)))
    if not path or not os.path.exists(path):
        print(f"ERROR: order PDF not found: {path}", file=sys.stderr)
        return 4
    print(json.dumps(extract(path), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
