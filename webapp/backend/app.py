"""
app.py
------
FastAPI backend for the order-tracking platform.

Endpoints:
  GET   /api/config                   -> current settings (root folder, db path)
  POST  /api/config                   -> update scan root folder
  GET   /api/orders                   -> order summaries (+ derived stage & completeness)
  GET   /api/orders/{dossier}         -> full order detail incl. documents
  PATCH /api/orders/{dossier}         -> save manual field edits (never touches dossier_no)
  POST  /api/orders/{dossier}/refresh -> re-scan source folder (fill-empty merge)
  POST  /api/scan                     -> walk the root folder and ingest all orders
  POST  /api/scan/new                 -> ingest only folders not yet in the DB

Run (from project root):
  zwick_venv_ericproject\\Scripts\\python -m uvicorn webapp.backend.app:app --reload --port 8000
"""
from __future__ import annotations

import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Make the project-root core modules importable (ingest, storage, ...).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
sys.path.insert(0, PROJECT_ROOT)

import ingest  # noqa: E402
import storage  # noqa: E402

from . import derive  # noqa: E402
from .settings import load_config, save_config  # noqa: E402

app = FastAPI(title="ZwickRoell Order Tracker", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _db_path() -> str:
    return load_config()["db_path"]


# Fields surfaced on dashboard cards (the prominent summary).
_SUMMARY_FIELDS = [
    "dossier_no",
    "order_id",
    "customer_name",
    "ship_to_address",
    "machine_type",
    "industry",
    "order_date",
    "shipping_date",
    "po_received_on",
    "received_oc_from_zrx",
    "packing_details_from_zrx",
    "rsm",
    "logistics_coordinator",
    "technical_contact",
    "shipping_contact",
    "updated_at",
    "cancelled",
]


def _summarize(order: dict) -> dict:
    summary = {f: order.get(f) for f in _SUMMARY_FIELDS}
    summary["stage"] = derive.derive_stage(order)
    summary["completeness"] = derive.derive_completeness(order)
    summary["is_active"] = derive.derive_active(order)
    return summary


@app.get("/api/config")
def get_config() -> dict:
    cfg = load_config()
    root = cfg["root_folder"]
    return {
        "root_folder": root,
        "db_path": cfg["db_path"],
        "root_exists": bool(root) and os.path.isdir(root),
    }


class ConfigUpdate(BaseModel):
    root_folder: str


@app.post("/api/config")
def update_config(update: ConfigUpdate) -> dict:
    root = (update.root_folder or "").strip().strip('"')
    save_config({"root_folder": root})
    return {
        "root_folder": root,
        "root_exists": bool(root) and os.path.isdir(root),
    }


@app.get("/api/orders")
def list_orders() -> dict:
    conn = storage.connect(_db_path())
    try:
        storage.init_db(conn)
        orders = storage.list_orders(conn)
    finally:
        conn.close()
    return {"orders": [_summarize(o) for o in orders], "count": len(orders)}


@app.get("/api/orders/{dossier}")
def get_order(dossier: str) -> dict:
    conn = storage.connect(_db_path())
    try:
        storage.init_db(conn)
        order = storage.get_order(conn, dossier)
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {dossier} not found")
        docs = storage.get_documents(conn, dossier)
    finally:
        conn.close()
    return {
        "order": order,
        "documents": docs,
        "stage": derive.derive_stage(order),
        "completeness": derive.derive_completeness(order),
    }


class OrderFieldsUpdate(BaseModel):
    fields: dict


@app.patch("/api/orders/{dossier}")
def patch_order(dossier: str, body: OrderFieldsUpdate) -> dict:
    """Save manual field edits from the UI drawer.

    Only whitelisted columns are written; dossier_no and updated_at are
    immutable.  Submitting an empty string for a field clears it.
    Returns the updated order with fresh stage and completeness.
    """
    conn = storage.connect(_db_path())
    try:
        storage.init_db(conn)
        updated = storage.update_order_fields(conn, dossier, body.fields)
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Order {dossier} not found")
        docs = storage.get_documents(conn, dossier)
    finally:
        conn.close()
    return {
        "order": updated,
        "documents": docs,
        "stage": derive.derive_stage(updated),
        "completeness": derive.derive_completeness(updated),
    }


@app.post("/api/orders/{dossier}/refresh")
def refresh_order(dossier: str) -> dict:
    """Re-scan the order's source folder in fill-empty mode.

    Fills only empty fields; never overwrites manually edited values.
    Documents are always refreshed so newly added files become visible.
    Returns the updated order with fresh stage, completeness, and documents.
    """
    cfg = load_config()
    try:
        result = ingest.refresh_order(dossier, db_path=cfg["db_path"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    order = result["order"]
    return {
        "order": order,
        "documents": result["documents"],
        "stage": derive.derive_stage(order),
        "completeness": derive.derive_completeness(order),
    }


@app.post("/api/scan")
def scan() -> dict:
    cfg = load_config()
    root = cfg["root_folder"]
    if not root or not os.path.isdir(root):
        raise HTTPException(status_code=400, detail=f"Configured root_folder is invalid: {root!r}")
    return ingest.scan_root(root, db_path=cfg["db_path"])


@app.post("/api/scan/new")
def scan_new() -> dict:
    cfg = load_config()
    root = cfg["root_folder"]
    if not root or not os.path.isdir(root):
        raise HTTPException(status_code=400, detail=f"Configured root_folder is invalid: {root!r}")
    return ingest.scan_new(root, db_path=cfg["db_path"])


# Serve the pre-built React app for all non-API routes.
# html=True enables SPA fallback: unknown paths return index.html.
if os.path.isdir(DIST_DIR):
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="spa")

