"""Entry point: point at a folder of invoices, extract, validate, store, export.

    python run.py "C:\\Invoices\\August"
"""

import argparse
import hashlib
import sys
from pathlib import Path

# Windows consoles default to cp1252, which can't encode the emoji status
# markers below. Force UTF-8 so output doesn't crash mid-batch.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import extractor
from export import XLSX_PATH, export_to_excel
from storage import init_db, is_duplicate, is_file_processed, save_invoice
from validation import validate_invoice

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def collect_files(folder: Path) -> list[Path]:
    files = [
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=lambda f: f.name)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def process_folder(folder: Path, model: str) -> dict:
    counts = {
        "processed": 0,
        "approved": 0,
        "needs_review": 0,
        "skipped": 0,
        "duplicate": 0,
        "failed": 0,
    }

    files = collect_files(folder)
    if not files:
        print(f"No supported invoice files found in {folder}")
        return counts

    for file_path in files:
        file_hash = sha256_of(file_path)

        if is_file_processed(file_hash):
            print(f"⏭️  {file_path.name} — skipped: already processed")
            counts["skipped"] += 1
            continue

        try:
            invoice = extractor.extract_invoice(str(file_path), model=model)
            flags = validate_invoice(invoice)

            if is_duplicate(invoice.supplier_abn, invoice.invoice_number):
                print(f"⚠️  {file_path.name} — duplicate: ABN {invoice.supplier_abn}, "
                      f"invoice {invoice.invoice_number} already exists")
                counts["duplicate"] += 1
                continue

            save_invoice(invoice, flags, file_path.name, file_hash)
            counts["processed"] += 1

            if flags:
                counts["needs_review"] += 1
                print(f"⚠️  {file_path.name} — needs review: {'; '.join(flags)}")
            else:
                counts["approved"] += 1
                print(f"✅ {file_path.name} — approved")

        except Exception as e:
            counts["failed"] += 1
            print(f"❌ {file_path.name} — failed: {e}")

    return counts


def print_summary(counts: dict):
    print("\n--- Summary ---")
    print(f"Processed:     {counts['processed']}")
    print(f"  Approved:    {counts['approved']}")
    print(f"  Needs review:{counts['needs_review']}")
    print(f"Skipped:       {counts['skipped']} (already processed)")
    print(f"Duplicates:    {counts['duplicate']}")
    print(f"Failed:        {counts['failed']}")


def main():
    parser = argparse.ArgumentParser(description="Extract invoice data from a folder into SQLite + Excel.")
    parser.add_argument("folder", type=str, help="Folder containing invoice PDFs/images")
    parser.add_argument("--model", type=str, default=extractor.MODEL,
                         help=f"Ollama vision model to use (default: {extractor.MODEL})")
    parser.add_argument("--export-only", action="store_true",
                         help="Skip processing and just regenerate the Excel workbook from the DB")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: folder does not exist: {folder}")
        sys.exit(1)

    init_db()
    xlsx_path = str(folder / XLSX_PATH)

    if args.export_only:
        export_to_excel(xlsx_path)
        return

    if not collect_files(folder):
        print(f"Error: no supported invoice files ({', '.join(sorted(SUPPORTED_EXTENSIONS))}) found in {folder}")
        sys.exit(1)

    counts = process_folder(folder, args.model)
    export_to_excel(xlsx_path)
    print_summary(counts)


if __name__ == "__main__":
    main()
