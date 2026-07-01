"""
app.py
------
FastAPI backend for the order-tracking platform.

Endpoints:
  GET  /api/config            -> current settings (root folder, db path)
  GET  /api/orders            -> order summaries (+ derived stage & completeness)
  GET  /api/orders/{dossier}  -> full order detail incl. documents
  POST /api/scan              -> walk the root folder and ingest all orders

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

