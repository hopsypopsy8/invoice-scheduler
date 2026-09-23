"""Regenerates invoices.xlsx from the SQLite database.

The DB is the source of truth: this file is completely overwritten from it on
every run. Manual edits to the xlsx are lost the next time this runs.
"""

import sys
from datetime import date
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from storage import get_all_invoices

# Windows consoles default to cp1252, which can't encode some characters used
# in the messages below. Force UTF-8 so this doesn't crash when run standalone.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

XLSX_PATH = "invoices.xlsx"
CURRENCY_FORMAT = '"$"#,##0.00'

INVOICE_COLUMNS = [
    ("Invoice Date", 14),
    ("Supplier", 32),
    ("ABN", 18),
    ("Invoice #", 18),
    ("Due Date", 14),
    ("Total", 12),
    ("GST", 12),
    ("Ex-GST", 12),
    ("Source File", 32),
    ("Flags", 60),
]

MONEY_COLUMNS = (6, 7, 8)  # Total, GST, Ex-GST
DATE_COLUMNS = (1, 5)  # Invoice Date, Due Date
NEEDS_REVIEW_FILL = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")


def _format_abn(abn: Optional[str]) -> str:
    if not abn:
        return ""
    digits = "".join(c for c in abn if c.isdigit())
    if len(digits) != 11:
        return abn
    return f"{digits[0:2]} {digits[2:5]} {digits[5:8]} {digits[8:11]}"


def _parse_date(value: Optional[str]):
    """Returns a date object for valid ISO strings, otherwise the raw value
    (so a malformed date is still visible to a reviewer instead of vanishing)."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return value


def _month_key(value: Optional[str]) -> Optional[str]:
    if not value or len(value) < 7:
        return None
    return value[:7]  # YYYY-MM


def _write_header(ws, columns):
    for col_idx, (name, width) in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=name)
        cell.font = Font(bold=True)
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.freeze_panes = "A2"


def _write_invoice_row(ws, row_idx: int, invoice: dict):
    total = invoice["total"]
    gst = invoice["gst"]
    ex_gst = round(total - gst, 2) if total is not None and gst is not None else None
    needs_review = invoice["status"] == "needs_review"

    values = [
        _parse_date(invoice["invoice_date"]),
        invoice["supplier_name"],
        _format_abn(invoice["supplier_abn"]),
        invoice["invoice_number"],
        _parse_date(invoice["due_date"]),
        total,
        gst,
        ex_gst,
        invoice["source_file"],
        invoice["validation_flags"] or "" if needs_review else "",
    ]

    for col_idx, value in enumerate(values, start=1):
        cell = ws.cell(row=row_idx, column=col_idx, value=value)
        if col_idx in MONEY_COLUMNS:
            cell.number_format = CURRENCY_FORMAT
        elif col_idx in DATE_COLUMNS and isinstance(value, date):
            cell.number_format = "yyyy-mm-dd"
        if needs_review:
            cell.fill = NEEDS_REVIEW_FILL


def _write_totals_row(ws, row_idx: int):
    label_cell = ws.cell(row=row_idx, column=1, value="Total")
    label_cell.font = Font(bold=True)
    has_data_rows = row_idx > 2
    for col_idx in MONEY_COLUMNS:
        col_letter = get_column_letter(col_idx)
        formula = f"=SUM({col_letter}2:{col_letter}{row_idx - 1})" if has_data_rows else 0
        cell = ws.cell(row=row_idx, column=col_idx, value=formula)
        cell.number_format = CURRENCY_FORMAT
        cell.font = Font(bold=True)


def _build_invoices_sheet(wb: Workbook, invoices: list[dict]):
    ws = wb.active
    ws.title = "Invoices"
    _write_header(ws, INVOICE_COLUMNS)

    invoices_sorted = sorted(invoices, key=lambda inv: inv["invoice_date"] or "")
    row_idx = 2
    for invoice in invoices_sorted:
        _write_invoice_row(ws, row_idx, invoice)
        row_idx += 1

    _write_totals_row(ws, row_idx)


def _build_monthly_summary_sheet(wb: Workbook, approved: list[dict]):
    ws = wb.create_sheet("Monthly Summary")
    columns = [
        ("Month", 12),
        ("Count", 10),
        ("Total Spend", 16),
        ("Total GST", 16),
        ("Total Ex-GST", 16),
    ]
    _write_header(ws, columns)

    months: dict[str, dict] = {}
    for invoice in approved:
        key = _month_key(invoice["invoice_date"])
        if key is None:
            continue
        bucket = months.setdefault(key, {"count": 0, "total": 0.0, "gst": 0.0})
        bucket["count"] += 1
        bucket["total"] += invoice["total"] or 0.0
        bucket["gst"] += invoice["gst"] or 0.0

    row_idx = 2
    for month in sorted(months):
        bucket = months[month]
        total = round(bucket["total"], 2)
        gst = round(bucket["gst"], 2)
        ex_gst = round(total - gst, 2)

        ws.cell(row=row_idx, column=1, value=month)
        ws.cell(row=row_idx, column=2, value=bucket["count"])
        for col_idx, amount in ((3, total), (4, gst), (5, ex_gst)):
            cell = ws.cell(row=row_idx, column=col_idx, value=amount)
            cell.number_format = CURRENCY_FORMAT
        row_idx += 1


def export_to_excel(xlsx_path: str = XLSX_PATH):
    all_invoices = get_all_invoices()
    approved = [inv for inv in all_invoices if inv["status"] == "approved"]
    needs_review = [inv for inv in all_invoices if inv["status"] == "needs_review"]

    wb = Workbook()
    _build_invoices_sheet(wb, all_invoices)
    _build_monthly_summary_sheet(wb, approved)

    try:
        wb.save(xlsx_path)
        print(f"Wrote {xlsx_path} ({len(approved)} approved, {len(needs_review)} needs review)")
    except PermissionError:
        print(f"Could not save {xlsx_path} — close it in Excel and rerun. "
              f"Nothing was lost: the database already has this data.")


if __name__ == "__main__":
    export_to_excel()
