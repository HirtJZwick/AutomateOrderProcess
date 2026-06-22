# Eric Automate Excel Sheet

Automates the transfer of ZwickRoell order data from a Word checklist (`.docx`) into the **FAT_INSTALL Plan Worksheet** (`.xlsx`), with a SQLite staging layer in between.

## How It Works

```
Checklist*.docx  →  extract  →  eric_orders.db (SQLite)  →  FAT_INSTALL*.xlsx
```

1. **Extract** – `extract_checklist.py` parses the ERP-generated Word checklist and pulls out order fields (customer, ship-to address, contacts, dates, service info, etc.).
2. **Stage** – `storage.py` upserts the extracted data into a local SQLite database (`eric_orders.db`), keyed on `dossier_no`. Re-running on the same order updates the existing row.
3. **Write** – `update_fat_plan.py` reads the staged order and writes specific cells in the `FAT Plan` sheet of the Excel workbook.

## Project Structure

| File | Purpose |
|---|---|
| `main.py` | Orchestrator – runs the full pipeline |
| `extract_checklist.py` | Word `.docx` parser |
| `storage.py` | SQLite read/write layer |
| `update_fat_plan.py` | Excel `.xlsx` writer |
| `run_python.ps1` | PowerShell wrapper invoked by Power Automate Desktop |
| `eric_orders.db` | SQLite database (auto-created on first run) |
| `FAT_INSTALL Plan Worksheet.xlsx` | Target Excel workbook |
| `logs/` | Runtime logs written by `run_python.ps1` |

## Requirements

- Python 3.10+
- Virtual environment at `zwick_venv_ericproject\`

Install dependencies into the venv:

```powershell
zwick_venv_ericproject\Scripts\pip install python-docx openpyxl
```

## Usage

### Run the full pipeline

```powershell
# Uses the newest Checklist*.docx found in the project folder
python main.py

# Or specify a path explicitly
python main.py "C:\path\to\Checklist DO737348 Order Report.docx"
```

### Run individual steps

```powershell
# Extract fields from a checklist and print JSON
python extract_checklist.py "Checklist DO737348 Order Report.docx"

# Write the most recent staged order to the workbook
python update_fat_plan.py

# Write a specific order by dossier number
python update_fat_plan.py 737348
```

### Via Power Automate Desktop

`run_python.ps1` wraps `main.py` for use in a Power Automate Desktop **Run application** action:

```powershell
.\run_python.ps1 -ScriptPath .\main.py -ScriptArgs "C:\path\to\Checklist....docx"
```

The script activates the venv Python, enforces UTF-8 encoding (for international customer names), and logs all runs to `logs\run_python.log`.

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `2` | Venv Python not found (`run_python.ps1`) |
| `3` | Script file not found (`run_python.ps1`) |
| `4` | Checklist `.docx` not found |
| `5` | No staged order in database |
| `6` | `FAT_INSTALL*.xlsx` workbook not found |
| `7` | Could not extract a Dossier No. from the checklist |

## Extracted Fields

Fields parsed from the checklist and stored in `eric_orders.db`:

- `dossier_no`, `order_id`, `account_no`, `customer_name`
- `ship_to_address`, `shipping_contact`, `technical_contact`
- `order_date`, `machine_type`, `industry`
- `po_received_on`, `customer_delivery_date_zru_oc`, `eta_for_sa`
- `send_po_to_zrx`, `send_order_acknowledgement`, `received_oc_from_zrx`
- `oc_sent_to_customer`, `packing_details_from_zrx`, `iqoq`
- `installation_required_hours`, `special_cal_gear_required`
- `technician`, `service_activity_done_by`, `sa`

## Excel Cells Written

| Cell | Value |
|---|---|
| `B2` | Document number (`DO<dossier_no>`) |
| `B3` | Customer name |
| `B4` | Install location (ship-to address) |
| `B19` | Customer contact name |
| `C19` | Customer company |
| `D19` | Contact phone |
| `E19` | Contact email |
