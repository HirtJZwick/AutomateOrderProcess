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

`folderPath` sent to the flows is a **path relative to the site/drive root**
(e.g. "/Documents/EricProject/<folder name>" for OneDrive, or
"/Freigegebene Dokumente/General/.../<folder name>" for a synced SharePoint
library), not the full local Windows path. The flow's "Get file metadata using
path" action resolves paths relative to the drive/site root — it cannot resolve
a local "C:/Users/..." path.

`_flow_folder_path()` converts the local path (as stored in the DB) into that
relative form, trying three strategies in order:

  1. An explicit mapping from config.json ("sharepoint_site_url" +
     "sharepoint_root_path"), relative to the configured "root_folder".
  2. The Windows OneDrive sync-root registry, which records the real remote
     URL behind every locally synced folder — this is what makes a synced
     **SharePoint library** (e.g. "C:\\Users\\<user>\\<Tenant>\\<Site> - <Lib>")
     resolvable, since such a path contains no "OneDrive - ..." segment.
  3. The legacy "OneDrive - <tenant>" segment strip (personal OneDrive).

Along with the path, the resolved **site address** is sent as `siteAddress` so a
flow using the SharePoint connector can point its "Site Address" at the right
site instead of hard-coding it.
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


# Windows records every locally synced OneDrive/SharePoint root here, together
# with the remote URL it maps to. This is the only reliable way to translate a
# synced **SharePoint library** path (which has no "OneDrive - ..." segment)
# back to its real location on the site.
_SYNC_ROOTS_KEY = r"Software\SyncEngines\Providers\OneDrive"


def _sync_roots() -> list[tuple[str, str, str]]:
    """(mount_point, full_remote_url, site_url) for every synced folder.

    Returns an empty list on non-Windows platforms, or if the registry key is
    missing/unreadable — callers then fall back to the other strategies.
    """
    try:
        import winreg
    except ImportError:
        return []

    roots: list[tuple[str, str, str]] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SYNC_ROOTS_KEY) as key:
            subkey_count = winreg.QueryInfoKey(key)[0]
            for i in range(subkey_count):
                try:
                    with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                        def _value(name: str) -> str:
                            try:
                                return str(winreg.QueryValueEx(sub, name)[0])
                            except OSError:
                                return ""

                        mount = _value("MountPoint")
                        remote = _value("FullRemotePath") or _value("UrlNamespace")
                        site = _value("WebUrl")
                        if mount and remote:
                            roots.append((mount, remote, site))
                except OSError:
                    continue
    except OSError:
        return []
    return roots


def _relative_to(folder_path: str, local_root: str) -> str | None:
    """Forward-slash remainder of `folder_path` inside `local_root`, or None.

    Returns "" when the two paths are the same folder.
    """
    if not local_root:
        return None
    target = os.path.normcase(os.path.normpath(folder_path))
    root = os.path.normcase(os.path.normpath(local_root))
    if target != root and not target.startswith(root + os.sep):
        return None
    remainder = os.path.normpath(folder_path)[len(os.path.normpath(local_root)):]
    return remainder.replace("\\", "/").strip("/")


def _join_url_path(base: str, remainder: str) -> str:
    base = base.rstrip("/")
    return f"{base}/{remainder}" if remainder else base


def _from_sync_registry(folder_path: str) -> tuple[str, str] | None:
    """Resolve via the Windows sync-root registry -> (site_relative_path, site_url).

    Picks the longest matching mount point so a nested sync root wins over a
    parent one.
    """
    best: tuple[str, str, str, str] | None = None  # (mount, remote, site, remainder)
    for mount, remote, site in _sync_roots():
        remainder = _relative_to(folder_path, mount)
        if remainder is None:
            continue
        if best is None or len(mount) > len(best[0]):
            best = (mount, remote, site, remainder)
    if best is None:
        return None

    _, remote, site, remainder = best
    full_url = _join_url_path(remote, remainder)
    site = (site or "").rstrip("/")
    if site and full_url.lower().startswith(site.lower()):
        return full_url[len(site):], site
    return full_url, site


def _from_config_mapping(folder_path: str) -> tuple[str, str] | None:
    """Resolve via an explicit config.json mapping -> (site_relative_path, site_url).

    Uses "root_folder" as the local prefix and "sharepoint_root_path" as the
    site-relative path it corresponds to. Lets an installation override the
    automatic detection (or work on a machine where the registry lookup fails).
    """
    try:
        from webapp.backend.settings import load_config

        cfg = load_config()
    except Exception:
        return None

    root_path = (cfg.get("sharepoint_root_path") or "").strip()
    if not root_path:
        return None
    remainder = _relative_to(folder_path, (cfg.get("root_folder") or "").strip())
    if remainder is None:
        return None
    relative = _join_url_path("/" + root_path.strip("/"), remainder)
    return relative, (cfg.get("sharepoint_site_url") or "").strip().rstrip("/")


def _flow_folder_path(folder_path: str) -> tuple[str, str]:
    """Convert a local synced path into (relative_path, site_address) for the flows.

    Tries the explicit config mapping, then the Windows sync-root registry, then
    the legacy "OneDrive - <tenant>" strip. `site_address` is "" for personal
    OneDrive (the OneDrive connector needs no site).
    """
    for resolver in (_from_config_mapping, _from_sync_registry):
        resolved = resolver(folder_path)
        if resolved:
            return resolved
    return _onedrive_relative_path(folder_path), ""


def _flow_succeeded(resp, flow_name: str, folder_path: str) -> bool:
    """True when the flow ran; otherwise log the status and body.

    Power Automate returns the failing action's error in the response body, so
    printing it turns an opaque "flow failed" line into something actionable.

    HTTP 202 and a 502 "NoResponse" are treated as success: the flow *was*
    accepted and is still running, it just outlived Power Automate's ~120 s
    synchronous response window. Its row still lands in the workbook, so the
    caller should go on waiting for it rather than declare a failure.
    """
    if resp.status_code == 200:
        return True
    body = (resp.text or "").strip().replace("\n", " ")[:500]
    if resp.status_code == 202 or (resp.status_code == 502 and "NoResponse" in body):
        print(
            f"{flow_name} is still running for {folder_path} (HTTP {resp.status_code}) — "
            f"its result will be picked up from the workbook once it finishes."
        )
        return True
    print(f"WARN: {flow_name} returned HTTP {resp.status_code} for {folder_path}: {body}")
    return False


def trigger_oc_contacts_flow(folder_path: str) -> bool:
    """POST {folderPath, siteAddress} to the OC Contacts flow. True on HTTP 200."""
    relative_path, site_address = _flow_folder_path(folder_path)
    print(
        f"Triggering OC contacts flow for folderPath: local={folder_path!r} "
        f"relative={relative_path!r} site={site_address!r}"
    )
    try:
        resp = requests.post(
            _configured_url("oc_contacts_flow_url", OC_CONTACTS_FLOW_URL),
            json={"folderPath": relative_path, "siteAddress": site_address},
            timeout=FLOW_TIMEOUT_SECONDS,
        )
        return _flow_succeeded(resp, "OC contacts flow", folder_path)
    except requests.RequestException as exc:
        print(f"WARN: OC contacts flow request failed for {folder_path}: {exc}")
        return False


def trigger_shipping_date_flow(dossier_no: str, folder_path: str) -> bool:
    """POST {dossier_no, folderPath, siteAddress} to the Shipping Date flow."""
    relative_path, site_address = _flow_folder_path(folder_path)
    print(
        f"Triggering shipping date flow for dossier_no: {dossier_no!r}, "
        f"folderPath: local={folder_path!r} relative={relative_path!r} site={site_address!r}"
    )
    try:
        resp = requests.post(
            _configured_url("shipping_date_flow_url", SHIPPING_DATE_FLOW_URL),
            json={
                "dossier_no": dossier_no,
                "folderPath": relative_path,
                "siteAddress": site_address,
            },
            timeout=FLOW_TIMEOUT_SECONDS,
        )
        return _flow_succeeded(resp, "shipping date flow", folder_path)
    except requests.RequestException as exc:
        print(f"WARN: shipping date flow request failed for {folder_path}: {exc}")
        return False
