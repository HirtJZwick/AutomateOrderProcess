"""
llm_extract.py
--------------
LLM-backed extraction for PDFs that are NOT structured like the Checklist.

Two extraction tasks, both via GitHub Models (gpt-5-mini):

  extract_order_contacts(pdf_path)
      Reads the (digital) Order PDF text and derives the ZwickRoell staff:
      logistics coordinator name + email, regional sales manager name + email.

  extract_shipping_date(pdf_path)
      Renders the (often scanned) shipping PDF to an image and reads the
      ship/delivery date off it.

The GitHub Models free tier caps each request at ~4000 tokens, so order text is
truncated and shipping pages are sent as compact JPEGs (vision input is tiled
and cheap) rather than as raw PDF bytes.
"""
from __future__ import annotations

import base64
import io
import json

import pdfplumber
from openai import OpenAI

import llm_config

# Keep order text well under the 4000-token request cap (~4 chars/token).
_MAX_TEXT_CHARS = 6000
_RENDER_RESOLUTION = 200  # DPI for PDF -> image rendering (higher = sharper digits)
_MAX_IMAGE_PAGES = 2

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=llm_config.BASE_URL, api_key=llm_config.GITHUB_TOKEN)
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
    raw = (raw or "").strip()
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
    "You are reading a ZwickRoell order confirmation document. "
    "Extract these internal ZwickRoell staff details:\n"
    "- logistics_coordinator: the Logistic & Sales Coordinator's full name\n"
    "- logistics_coordinator_email: that person's email\n"
    "- rsm: the Regional Sales Manager's full name\n"
    "- rsm_email: the Regional Sales Manager's email\n"
    "Reply with ONLY a JSON object with exactly those four keys. "
    "Use null for any value you cannot find."
)


def extract_order_contacts(pdf_path: str) -> dict:
    """Derive logistics + RSM contacts from an Order PDF via the LLM."""
    text = _pdf_text(pdf_path, max_pages=2)[:_MAX_TEXT_CHARS]
    if not text.strip():
        return {}

    response = _get_client().chat.completions.create(
        model=llm_config.MODEL,
        messages=[
            {"role": "system", "content": _CONTACT_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    parsed = _parse_json(response.choices[0].message.content)
    allowed = {"logistics_coordinator", "logistics_coordinator_email", "rsm", "rsm_email"}
    return _drop_empty({k: parsed.get(k) for k in allowed})


# --------------------------------------------------------------------------- #
# Shipping PDF -> ship date (image-based, scanned docs)
# --------------------------------------------------------------------------- #
_SHIP_PROMPT = (
    "This is a scanned freight delivery receipt / proof of delivery. "
    "Find the delivery date: look near labels like 'Result', 'Delivered', "
    "'Date', or 'Ship'. It is usually next to the word 'Date' in the "
    "results/signature area at the bottom. Read the digits carefully. "
    'Reply with ONLY a JSON object: {"shipping_date": "M/D/YYYY"}. '
    "Normalise any 2-digit year to 4 digits (e.g. 26 -> 2026). "
    'If no date is found, reply: {"shipping_date": null}'
)


def extract_shipping_date(pdf_path: str) -> dict:
    """Derive the shipping date from a (scanned) shipping PDF via the LLM."""
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
        model=llm_config.MODEL,
        messages=[
            {
                "role": "user",
                "content": [*image_parts, {"type": "text", "text": _SHIP_PROMPT}],
            }
        ],
    )
    return _drop_empty(_parse_json(response.choices[0].message.content))
