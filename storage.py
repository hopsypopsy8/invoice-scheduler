import sqlite3
from datetime import datetime
from typing import Optional

DB_PATH = "invoices.db"


def init_db(db_path: str = DB_PATH):
    """Creates the invoices table if it doesn't already exist. Safe to call every run."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_name TEXT,
            supplier_abn TEXT,
            invoice_number TEXT,
            invoice_date TEXT,
            due_date TEXT,
            subtotal REAL,
            gst REAL,
            total REAL,
            status TEXT,
            source_file TEXT,
            file_hash TEXT UNIQUE,
            validation_flags TEXT,
            date_added TEXT,
            UNIQUE(supplier_abn, invoice_number)
        )
    """)
    conn.commit()
    conn.close()


def normalise_abn(abn: Optional[str]) -> Optional[str]:
    """Strip everything except digits, so '76 096 304 620' and '76096304620' match."""
    if not abn:
        return None
    digits = "".join(c for c in abn if c.isdigit())
    return digits or None


def is_duplicate(supplier_abn: Optional[str], invoice_number: Optional[str], db_path: str = DB_PATH) -> bool:
    """Checks whether an invoice with this ABN + invoice number is already stored."""
    supplier_abn = normalise_abn(supplier_abn)
    if not supplier_abn or not invoice_number:
        return False  # can't check without both — let it through, flag separately if needed

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM invoices WHERE supplier_abn = ? AND invoice_number = ?",
        (supplier_abn, invoice_number),
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None


def is_file_processed(file_hash: str, db_path: str = DB_PATH) -> bool:
    """Checks whether a file with this SHA-256 hash has already been processed."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM invoices WHERE file_hash = ?", (file_hash,))
    result = cursor.fetchone()
    conn.close()
    return result is not None


def save_invoice(
    invoice,
    validation_flags: list[str],
    source_file: str,
    file_hash: str,
    db_path: str = DB_PATH,
) -> int:
    """
    Saves an invoice to the database.
    `invoice` is your Pydantic Invoice object from extractor.py.
    Status is derived from validation_flags: 'approved' if empty, else 'needs_review'.
    Returns the new row's id.
    Raises sqlite3.IntegrityError if it's a duplicate (same ABN + invoice number, or same file_hash).
    """
    status = "needs_review" if validation_flags else "approved"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO invoices (
            supplier_name, supplier_abn, invoice_number, invoice_date,
            due_date, subtotal, gst, total, status, source_file,
            file_hash, validation_flags, date_added
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        invoice.supplier_name,
        normalise_abn(invoice.supplier_abn),
        invoice.invoice_number,
        invoice.invoice_date,
        invoice.due_date,
        invoice.subtotal,
        invoice.gst,
        invoice.total,
        status,
        source_file,
        file_hash,
        " | ".join(validation_flags) if validation_flags else None,
        datetime.now().isoformat(),
    ))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def get_all_invoices(db_path: str = DB_PATH) -> list[dict]:
    """Returns every stored invoice as a list of dicts, most recent first."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM invoices ORDER BY date_added DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

if __name__ == "__main__":
    init_db()
    print("Database initialised. Check for invoices.db in this folder.")
