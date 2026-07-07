"""
llm_extract_phi.py
------------------
LLM-backed extraction for PDFs using Phi-4-reasoning via GitHub Models.

Drop-in replacement for llm_extract.py with the same public interface:

  extract_order_contacts(pdf_paths)
      Reads text from all provided Order PDFs and derives the ZwickRoell staff:
      logistics coordinator name + email, regional sales manager name + email.
      Sends all text in a single LLM call for full context.

  extract_shipping_date(pdf_path)
      Renders the (often scanned) shipping PDF to an image and reads the
      ship/delivery date off it. Uses the multimodal gpt-5-mini fallback since
      phi-4-reasoning is text-only.

Phi-4-reasoning is text-only, so contacts are extracted via concatenated PDF
text. Shipping date extraction (which needs vision for scanned docs) falls back
to llm_extract.py (gpt-5-mini multimodal).
"""
from __future__ import annotations

import base64
import io
import json
import os

import pdfplumber
from openai import OpenAI

import llm_config

_MAX_TEXT_CHARS_PER_PDF = 4000   # chars extracted per PDF before concatenation
_MAX_TOTAL_TEXT_CHARS = 12000    # total chars sent to the model across all PDFs
_RENDER_RESOLUTION = 200         # DPI for PDF → image rendering (shipping date)
_MAX_IMAGE_PAGES = 2             # pages per PDF for shipping date extraction

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=llm_config.BASE_URL,
            api_key=llm_config.GITHUB_TOKEN,
        )
    return _client


# --------------------------------------------------------------------------- #
# PDF helpers
# --------------------------------------------------------------------------- #
def _pdf_text(pdf_path: str, max_pages: int = 2) -> str:
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:max_pages]:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def _pdf_images_b64(pdf_path: str, max_pages: int = _MAX_IMAGE_PAGES) -> list[str]:
    """Render the first pages to base64 JPEGs for vision input."""
    images = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:max_pages]:
            pil_img = page.to_image(resolution=_RENDER_RESOLUTION).original
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=70)
            images.append(base64.standard_b64encode(buf.getvalue()).decode("utf-8"))
    return images


def _parse_json(raw: str) -> dict:
    """Extract a JSON object from the model response.

    Reasoning models (like phi-4-reasoning) output a verbose chain-of-thought
    before the final answer, so we search for the LAST { ... } block in the
    response rather than the first.
    """
    raw = (raw or "").strip()
    # Find the last JSON object in the response (handles reasoning model output)
    last_brace = raw.rfind("{")
    if last_brace != -1:
        candidate = raw[last_brace:]
        # Find matching closing brace
        depth = 0
        for i, ch in enumerate(candidate):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(candidate[:i + 1])
                    except (json.JSONDecodeError, ValueError):
                        break
    # Fallback: try the whole string (handles ```json blocks)
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}


def _drop_empty(data: dict) -> dict:
    """Drop None / empty values so they never overwrite good data on upsert."""
    return {k: v for k, v in data.items() if v not in (None, "", "null")}


# --------------------------------------------------------------------------- #
# Order PDF -> ZwickRoell contacts (text-based)
# --------------------------------------------------------------------------- #
_CONTACT_PROMPT = (
    "You are reading ZwickRoell documents that are part of an order folder. "
    "Extract these internal ZwickRoell staff details:\n"
    "- logistics_coordinator: the Logistic & Sales Coordinator's full name\n from ZwickRoell \n"
    "- logistics_coordinator_email: that person's email from ZwickRoell\n"
    "- rsm: the Regional Sales Manager's full name\n from ZwickRoell \n"
    "- rsm_email: the Regional Sales Manager's email from ZwickRoell\n"
    "If any of these details are not present, use null for that value."
    "Reply with ONLY a JSON object with exactly those four keys. "
    "Use null for any value you cannot find."
)


def extract_order_contacts(pdf_paths: list[str]) -> dict:
    """Derive logistics + RSM contacts from a list of PDFs via Phi-4-reasoning.

    Concatenates extracted text from all PDFs (up to _MAX_TOTAL_TEXT_CHARS total)
    and sends it in a single text-based LLM call. Each PDF's text is labelled with
    its filename so the model has full context across all documents.
    """
    if not pdf_paths:
        return {}

    sections: list[str] = []
    total_chars = 0
    for pdf_path in pdf_paths:
        if total_chars >= _MAX_TOTAL_TEXT_CHARS:
            break
        text = _pdf_text(pdf_path, max_pages=3)[:_MAX_TEXT_CHARS_PER_PDF]
        if text.strip():
            remaining = _MAX_TOTAL_TEXT_CHARS - total_chars
            chunk = text[:remaining]
            sections.append(f"=== {os.path.basename(pdf_path)} ===\n{chunk}")
            total_chars += len(chunk)

    if not sections:
        return {}

    combined_text = "\n\n".join(sections)
    response = _get_client().chat.completions.create(
        model=llm_config.PHI_MODEL,
        messages=[
            {"role": "user", "content": f"{_CONTACT_PROMPT}\n\n{combined_text}"},
        ],
    )
    parsed = _parse_json(response.choices[0].message.content)
    allowed = {"logistics_coordinator", "logistics_coordinator_email", "rsm", "rsm_email"}
    result = _drop_empty({k: parsed.get(k) for k in allowed})
    # Reasoning models sometimes insert spaces into email addresses — strip them.
    for email_key in ("logistics_coordinator_email", "rsm_email"):
        if email_key in result:
            result[email_key] = result[email_key].replace(" ", "")
    return result


# --------------------------------------------------------------------------- #
# Shipping PDF -> ship date (image-based, scanned docs)
# --------------------------------------------------------------------------- #
_SHIP_PROMPT = (
    "This is a scanned freight delivery receipt / proof of delivery. "
    "Find the delivery date: look near labels like 'Result', 'Delivered', "
    "'Date', 'Ship' or 'Flight'. Usually when it was shipped using a plane, the flight date indicates the shipping date. "
    "Read the digits carefully. "
    'Reply with ONLY a JSON object: {"shipping_date": "M/D/YYYY"}. '
    "Normalise any 2-digit year to 4 digits (e.g. 26 -> 2026). "
    'If no date is found, reply: {"shipping_date": null}'
)


def extract_shipping_date(pdf_path: str) -> dict:
    """Derive the shipping date from a (scanned) shipping PDF via Phi-4 multimodal."""
    image_parts = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
        }
        for b64 in _pdf_images_b64(pdf_path)
    ]
    if not image_parts:
        return {}

    response = _get_client().chat.completions.create(
        model=llm_config.PHI_MODEL,
        messages=[
            {
                "role": "user",
                "content": [*image_parts, {"type": "text", "text": _SHIP_PROMPT}],
            }
        ],
    )
    return _drop_empty(_parse_json(response.choices[0].message.content))


# --------------------------------------------------------------------------- #
# Console test runner
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys
    import json as _json
    import extract_order_pdf

    if len(sys.argv) < 2:
        print("Usage: python llm_extract_phi.py <order_folder>")
        sys.exit(1)

    folder = sys.argv[1]
    pdfs = extract_order_pdf.find_all_pdfs(folder)

    if not pdfs:
        print("No PDFs found in folder:", folder)
        sys.exit(0)

    print(f"Found {len(pdfs)} PDF(s):")
    for p in pdfs:
        print(f"  {p}")
    print()

    print("Extracting contacts (single multimodal call)...")
    result = extract_order_contacts(pdfs)
    print(_json.dumps(result, indent=2, ensure_ascii=False))
