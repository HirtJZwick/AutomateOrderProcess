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
    cfg = {"root_folder": "", "db_path": "eric_orders.db"}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
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
    for key in ("root_folder", "db_path"):
        if key in updates and updates[key] is not None:
            cfg[key] = updates[key]
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    return cfg
