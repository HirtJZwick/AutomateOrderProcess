"""
settings.py
-----------
Load platform configuration from config.json at the project root.
"""
from __future__ import annotations

import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")


def _raw_config() -> dict:
    cfg = {
        "root_folder": "",
        "db_path": "eric_orders.db",
        # Power Automate flow HTTP-trigger URLs and the local OneDrive-synced
        # folder holding the two workbooks they write to. Each installation
        # (dev, Eric, ...) has its own flows/workbooks, so these are blank by
        # default here and must be set per-machine in config.json. When blank,
        # excel_sync.py / power_automate.py fall back to their own hard-coded
        # defaults (the developer's setup) for backwards compatibility.
        "oc_contacts_flow_url": "",
        "shipping_date_flow_url": "",
        "excel_root": "",
        # Optional overrides for translating the local synced order folder into
        # the SharePoint path the flows need. Leave blank to let
        # power_automate.py detect it automatically from the Windows OneDrive
        # sync-root registry. Set them when auto-detection is unavailable, e.g.
        #   "sharepoint_site_url":  "https://contoso.sharepoint.com/sites/MySite"
        #   "sharepoint_root_path": "/Shared Documents/General/Order_Folder"
        # where sharepoint_root_path is the site-relative path that
        # "root_folder" corresponds to on SharePoint.
        "sharepoint_site_url": "",
        "sharepoint_root_path": "",
        # How long (seconds) to wait for a flow's row to reach the local
        # OneDrive-synced copy of the result workbooks. The flows answer
        # HTTP 200 as soon as they have written to SharePoint; the local file
        # follows once OneDrive has synchronized it, which was measured at
        # roughly 30 seconds. Set to 0 to disable waiting.
        "flow_result_timeout_seconds": 90,
    }
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as fh:
            cfg.update(json.load(fh))
    return cfg


def load_config() -> dict:
    cfg = _raw_config()
    # Resolve a relative db_path against the project root.
    if not os.path.isabs(cfg["db_path"]):
        cfg["db_path"] = os.path.join(PROJECT_ROOT, cfg["db_path"])
    return cfg


def save_config(updates: dict) -> dict:
    """Merge `updates` into config.json (only known keys) and return raw config."""
    cfg = _raw_config()
    for key in (
        "root_folder",
        "db_path",
        "oc_contacts_flow_url",
        "shipping_date_flow_url",
        "excel_root",
        "sharepoint_site_url",
        "sharepoint_root_path",
        "flow_result_timeout_seconds",
    ):
        if key in updates and updates[key] is not None:
            cfg[key] = updates[key]
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return cfg
