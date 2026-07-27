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
    ):
        if key in updates and updates[key] is not None:
            cfg[key] = updates[key]
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return cfg
