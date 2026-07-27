"""
power_automate.py
------------------
Triggers the two Power Automate HTTP-triggered flows that replaced local LLM
extraction:

  trigger_oc_contacts_flow(folder_path)
      Fires the "OC Contacts" flow, which reads the order's Order Confirmation
      documents (via its own SharePoint/OneDrive connector) and writes the
      logistics coordinator + RSM contact details to the shared
      OC_Contacts.xlsx workbook (see excel_sync.py).

  trigger_shipping_date_flow(dossier_no, folder_path)
      Fires the "Shipping Date" flow, which reads the order's shipping/invoice
      documents and writes the shipping date to the shared
      Dossier_Shipping_Date.xlsx workbook (see excel_sync.py).

Both calls are synchronous: each flow's HTTP trigger only responds (200) once
it has finished writing to its workbook, so callers can safely read the
workbook immediately after a successful call. Neither function raises on
failure — they return False and print a WARN message, mirroring the previous
LLM-call warning behavior in ingest.py, so a flaky flow never crashes ingestion.

`folderPath` sent to the flows is a **OneDrive-relative path** (e.g.
"/Documents/EricProject/<folder name>"), not the full local Windows path.
The flow's "Get file metadata using path" action uses the OneDrive for
Business connector, which resolves paths relative to the OneDrive drive
root — it cannot resolve a local "C:/Users/..." path. `_onedrive_relative_path()`
converts the local `source_folder` path (as stored in the DB) into that
relative form by stripping everything up to and including the
"OneDrive - <tenant>" folder segment.
"""
from __future__ import annotations

import os

import requests

# Fallback defaults (the developer's own flows). Each installation should
# normally set its own "oc_contacts_flow_url" / "shipping_date_flow_url" in
# config.json instead — see webapp/backend/settings.py — since every person
# running this app needs their own Power Automate flows (a flow can only
# write into workbooks it has been granted access to). These constants only
# exist so an install with no config.json override keeps working as before.
OC_CONTACTS_FLOW_URL = (
    "https://4f44d0967de9e2629f0d37cc1dbdf9.01.environment.api.powerplatform.com:443"
    "/powerautomate/automations/direct/cu/24/workflows/4335734a62ce44d5aba333a45a2ec004"
    "/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0"
    "&sig=FPbShrUBTSpckQf730TtZPqWVE4aXnt2GxKBuLdEBzM"
)
SHIPPING_DATE_FLOW_URL = (
    "https://4f44d0967de9e2629f0d37cc1dbdf9.01.environment.api.powerplatform.com:443"
    "/powerautomate/automations/direct/cu/02/workflows/7e1bcb23f07c4eccabac6d93ab878f9b"
    "/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0"
    "&sig=5shM9VjfQbJi4XmjFgy_LiYfCBvanLTO-vSETRLU7fo"
)

# Flows can take a while to read and process documents; wait generously.
FLOW_TIMEOUT_SECONDS = 300


def _configured_url(config_key: str, default_url: str) -> str:
    """Return the flow URL from config.json's `config_key`, falling back to
    `default_url` (this module's hard-coded default) if unset/blank."""
    try:
        from webapp.backend.settings import load_config

        configured = load_config().get(config_key)
    except Exception:
        configured = None
    return configured or default_url


def _onedrive_relative_path(folder_path: str) -> str:
    """Convert a local OneDrive-synced path into a path relative to the
    OneDrive drive root, as expected by the OneDrive for Business connector.

    e.g. "C:\\Users\\Hirtj\\OneDrive - ZwickRoell GmbH & Co. KG\\Documents\\
    EricProject\\DO001 ACME" -> "/Documents/EricProject/DO001 ACME"

    Falls back to the original path (with backslashes converted to forward
    slashes) if no "OneDrive - ..." segment is found, so a misconfigured path
    still gets sent rather than raising.
    """
    parts = os.path.normpath(folder_path).split(os.sep)
    idx = next(
        (i for i, part in enumerate(parts) if part.lower().startswith("onedrive - ")),
        None,
    )
    if idx is None:
        print(f"WARN: could not find 'OneDrive - ...' segment in {folder_path!r}; sending path as-is")
        return folder_path.replace("\\", "/")
    relative = "/".join(parts[idx + 1:])
    return "/" + relative


def trigger_oc_contacts_flow(folder_path: str) -> bool:
    """POST {folderPath} to the OC Contacts flow. Returns True on HTTP 200."""
    relative_path = _onedrive_relative_path(folder_path)
    print(f"Triggering OC contacts flow for folderPath: local={folder_path!r} relative={relative_path!r}")
    try:
        resp = requests.post(
            _configured_url("oc_contacts_flow_url", OC_CONTACTS_FLOW_URL),
            json={"folderPath": relative_path},
            timeout=FLOW_TIMEOUT_SECONDS,
        )
        return resp.status_code == 200
    except requests.RequestException as exc:
        print(f"WARN: OC contacts flow request failed for {folder_path}: {exc}")
        return False


def trigger_shipping_date_flow(dossier_no: str, folder_path: str) -> bool:
    """POST {dossier_no, folderPath} to the Shipping Date flow. True on HTTP 200."""
    relative_path = _onedrive_relative_path(folder_path)
    print(
        f"Triggering shipping date flow for dossier_no: {dossier_no!r}, "
        f"folderPath: local={folder_path!r} relative={relative_path!r}"
    )
    try:
        resp = requests.post(
            _configured_url("shipping_date_flow_url", SHIPPING_DATE_FLOW_URL),
            json={"dossier_no": dossier_no, "folderPath": relative_path},
            timeout=FLOW_TIMEOUT_SECONDS,
        )
        return resp.status_code == 200
    except requests.RequestException as exc:
        print(f"WARN: shipping date flow request failed for {folder_path}: {exc}")
        return False
