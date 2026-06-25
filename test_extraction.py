r"""
test_extraction.py
------------------
Manual smoke test for the LLM-based PDF extraction.
Run directly — no arguments needed:

    zwick_venv_ericproject\Scripts\python test_extraction.py

Edit the paths below to point at a real order folder / shipping PDF.
"""
from __future__ import annotations

import json

import extract_order_pdf
import llm_extract

# --- Configure here -------------------------------------------------------
ORDER_FOLDER = (
    r"C:\Users\Hirtj\OneDrive - ZwickRoell GmbH & Co. KG\Documents\EricProject"
    r"\SAR07661_University of Connecticut_OPP432918"
)
# -------------------------------------------------------------------------


def main() -> None:
    print(f"Order folder: {ORDER_FOLDER}\n" + "-" * 60)

    order_pdf = extract_order_pdf.find_order_pdf(ORDER_FOLDER)
    print(f"Order PDF: {order_pdf}")
    if order_pdf:
        contacts = llm_extract.extract_order_contacts(order_pdf)
        print("Contacts:", json.dumps(contacts, indent=2))

    print("-" * 60)
    shipping_pdfs = extract_order_pdf.find_shipping_pdfs(ORDER_FOLDER)
    print(f"Shipping PDFs found: {len(shipping_pdfs)}")
    for pdf in shipping_pdfs:
        result = llm_extract.extract_shipping_date(pdf)
        print(f"  {pdf}\n    -> {json.dumps(result)}")
        if result.get("shipping_date"):
            break


if __name__ == "__main__":
    main()
