# ZwickRoell Order Tracker

A locally-hosted platform that extracts order data from ZwickRoell order
documents and visualizes each order's progress, so Eric can see status at a
glance before talking to a customer.

## How It Works

```
order folders (.docx / .pdf)
        │
        ▼
  parse + extract        (extract_checklist.py, extract_order_pdf.py)
        │
        ▼
  SQLite  eric_orders.db (storage.py)
        │
        ▼
  FastAPI JSON API       (webapp/backend)
        │
        ▼
  React + Vite UI        (webapp/frontend)
```

1. **Extract** – `extract_checklist.py` parses the ERP checklist `.docx`;
   `extract_order_pdf.py` parses an *Order* PDF for the ZwickRoell contacts
   (Regional Sales Manager, Logistics Coordinator).
2. **Ingest** – `ingest.py` merges both, records which documents are present,
   and upserts into the SQLite database (keyed on `dossier_no`).
3. **Serve** – a FastAPI backend exposes the data as JSON, including a derived
   high-level **stage** and **completeness** score.
4. **Visualize** – a React/Vite dashboard shows color-coded order cards with an
   expandable detail view.

## Project Structure

| Path | Purpose |
|---|---|
| `extract_checklist.py` | Word `.docx` checklist parser |
| `extract_order_pdf.py` | *Order* PDF parser (ZwickRoell contacts) |
| `storage.py` | SQLite read/write layer (orders + documents) |
| `ingest.py` | Core ingestion: `ingest_folder()` + `scan_root()` |
| `config.json` | Settings: `root_folder`, `db_path` |
| `webapp/backend/` | FastAPI app (`app.py`, `settings.py`, `derive.py`) |
| `webapp/frontend/` | React + Vite dashboard |
| `excel_legacy/` | **Retired** Excel write-back (`update_fat_plan.py`, `milestone_status.py`, `main.py`) — kept for reference, not part of the active flow |
| `eric_orders.db` | SQLite database (auto-created) |

## Requirements

- **Python 3.10+** with the venv at `zwick_venv_ericproject\`
- **Node.js 18+** (for the frontend)

Install Python dependencies:

```powershell
zwick_venv_ericproject\Scripts\pip install python-docx openpyxl pdfplumber fastapi "uvicorn[standard]"
```

## Configuration

Edit `config.json` to point at the folder that contains all order folders:

```json
{
  "root_folder": "C:\\path\\to\\OneDrive_2_6-18-2026",
  "db_path": "eric_orders.db"
}
```

## Running the Platform

**1. Start the backend** (from the project root):

```powershell
zwick_venv_ericproject\Scripts\python -m uvicorn webapp.backend.app:app --reload --port 8000
```

**2. Start the frontend** (in `webapp/frontend`):

```powershell
npm install      # first time only
npm run dev
```

Then open **http://localhost:5173**. Click **"Scan orders"** to walk the
configured `root_folder`, extract every order folder (any folder containing a
`Checklist*.docx`), and load them into the database. The dev server proxies
`/api` to the backend automatically.

## Dashboard

- **Order cards** show customer, dossier/order id, machine, key dates and the
  primary contact, color-coded by stage.
- **Stage band** (derived directly from the checklist dates, no rule engine):
  `New → Order Confirmed → Packed → Shipped`.
  - Shipped: invoice / collection-tracking / customer-informed date present
  - Packed: packing-details date present
  - Order Confirmed: OC-received / OC-sent date present
- **Completeness bar** shows how much expected information was extracted
  (green = full, amber = partial, red = low, grey = missing).
- Click a card (or open `/?order=<dossier>`) for the full detail drawer:
  overview, contacts, order-processing timeline, service info and the list of
  documents found in the folder.

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/config` | Current root folder / db path |
| `GET` | `/api/orders` | Order summaries (+ derived stage & completeness) |
| `GET` | `/api/orders/{dossier}` | Full order detail incl. documents |
| `POST` | `/api/scan` | Walk the root folder and ingest all orders |

## Legacy: Excel write-back

The earlier workflow that wrote data and inferred milestone statuses back into
the **FAT_INSTALL Plan Worksheet** lives in `excel_legacy/` and is no longer part
of the active pipeline. It still runs standalone if needed:

```powershell
zwick_venv_ericproject\Scripts\python excel_legacy\main.py "C:\path\to\Checklist ....docx"
```

## Notes

- This is a **prototype** intended for demo and iteration.
- The rule-based milestone inference (`excel_legacy/milestone_status.py`) is
  intentionally **not** used by the website; the dashboard derives a simpler
  stage directly from the data. It may be revisited later.
