"""
extract_order_pdf.py
--------------------
Extract ZwickRoell contacts and header references from an "Order" PDF
(e.g. "DO737348 Order Confirmation.pdf").

The Checklist .docx does NOT contain the internal ZwickRoell staff who own the
order. The Order Confirmation PDF does, in a small "Your ZwickRoell contacts are:"
block, e.g.:

    Logistic & Sales Coordinator   Anita Boyd
    Order Processing & Logistics   Tel. (678) 695-5752
                                   anita.boyd@zwickroell.com
    Regional Sales Manager         Shaun Potts
                                   Shaun.Potts@zwickroell.com

We parse the Regional Sales Manager (RSM) and the Logistic & Sales Coordinator.
Other roles (e.g. Technical Manager) are intentionally ignored.

Usage:
    python extract_order_pdf.py "C:\\path\\to\\DO737348 Order Confirmation.pdf"
    # prints the parsed field dict as JSON
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

import pdfplumber

# Role label -> output key prefix. Order here also defines slice boundaries.
# A role is mapped to None when we recognise it (to bound the slice) but do not
# want to keep it.
ROLE_SPECS = [
    ("logistics_coordinator", r"Logistic[^\n]*Coordinator"),
    ("technical_manager", r"Technical Manager"),     # boundary only, not kept
    ("rsm", r"Regional Sales Manager"),
]

KEEP_ROLES = {"logistics_coordinator", "rsm"}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_PHONE_RE = re.compile(r"(?:Tel\.?\s*)?(\+?\d?[\s.]*\(?\d{3}\)?[\s.\-]*\d{3}[\s.\-]*\d{4})")


def read_text(pdf_path: str, max_pages: int = 2) -> str:
    """Return the concatenated text of the first `max_pages` pages."""
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:max_pages]:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def _contacts_block(text: str) -> str:
    """Return the text following the 'ZwickRoell contacts are:' marker."""
    m = re.search(r"ZwickRoell contacts are:?(.*)", text, re.S | re.I)
    return m.group(1) if m else text


def _clean_phone(raw: str) -> str | None:
    m = _PHONE_RE.search(raw)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip()


def parse_contacts(text: str) -> dict:
    """Parse the ZwickRoell contact block into name/phone/email per kept role."""
    block = _contacts_block(text)

    # Locate every recognised role label so we can slice between them.
    anchors = []
    for key, pat in ROLE_SPECS:
        for m in re.finditer(pat, block, re.I):
            anchors.append((m.start(), m.end(), key))
    anchors.sort()

    out: dict = {}
    for i, (start, end, key) in enumerate(anchors):
        seg_end = anchors[i + 1][0] if i + 1 < len(anchors) else len(block)
        segment = block[end:seg_end]
        if key not in KEEP_ROLES:
            continue

        # A contact entry is at most ~3 lines (name line, description+Tel line,
        # email line). Scope the search to those lines so we never bleed into the
        # next entry, the letter body, or a page footer.
        lines = segment.splitlines()

        # Name is the remainder of the label's own line.
        name = lines[0].strip() if lines else ""
        name = re.sub(r"\s+", " ", name).strip(" /-")

        phone = _clean_phone("\n".join(lines[:2]))
        email = _EMAIL_RE.search("\n".join(lines[:3]))

        out[key] = name or None
        out[f"{key}_phone"] = phone
        out[f"{key}_email"] = email.group(0) if email else None
    return out


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
    text = read_text(pdf_path)
    data: dict = {"oc_source_file": os.path.basename(pdf_path)}
    data.update(parse_header(text))
    data.update(parse_contacts(text))
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


def main(argv):
    if len(argv) > 1:
        path = argv[1]
    else:
        path = find_order_pdf(os.path.dirname(os.path.abspath(__file__)))
    if not path or not os.path.exists(path):
        print(f"ERROR: order PDF not found: {path}", file=sys.stderr)
        return 4
    print(json.dumps(extract(path), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
