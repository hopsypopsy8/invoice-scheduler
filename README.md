# Invoice Scheduler

A small tool for turning a folder of invoice PDFs/images into structured,
validated data — without sending anything to the cloud.

## Why

Bookkeeping for a small business usually means opening a pile of invoice PDFs
one at a time to copy the supplier, ABN, invoice number, date, and GST/total
into a spreadsheet by hand. It's slow and error-prone, and invoice data
(supplier details, ABNs, amounts) isn't something you necessarily want to hand
to a cloud API just to automate data entry.

This tool points at a folder, reads each invoice with a **local** vision
model running through [Ollama](https://ollama.com), and does simple
arithmetic-based validation (ABN checksum, GST reconciliation, date sanity
checks) to flag anything that looks like a misread rather than silently
trusting the model. Clean invoices are marked approved; anything flagged goes
to `needs_review` so a human gives it one glance instead of re-keying every
field. Everything is stored in SQLite and re-exported to Excel on every run.

Nothing leaves the machine: no cloud OCR, no cloud LLM API.

## How it works

```
run.py          entry point: CLI, loops the folder, orchestrates, prints a summary
extractor.py    file -> images -> Ollama vision call -> structured Invoice
validation.py   arithmetic/format checks -> list of flags per invoice
storage.py      SQLite persistence, deduplication (by file hash and by ABN + invoice number)
export.py       regenerates the Excel workbook from the database
```

Each file is hashed (SHA-256) before processing, so re-running the tool on a
folder never reprocesses a file it's already seen. If the same invoice shows
up again under a different filename (e.g. forwarded as a scan instead of the
original PDF), it's caught by matching ABN + invoice number instead, and
skipped as a duplicate. A failure on one file (corrupt PDF, model error) never
stops the batch — it's logged and the rest of the folder still processes.

## Setup

```
pip install -r requirements.txt
```

Requires [Ollama](https://ollama.com) running locally with a vision-capable
model pulled. The default is `gemma3:12b`:

```
ollama pull gemma3:12b
```

`qwen2.5vl:7b` has also been tested and works as a drop-in alternative if you
want something lighter — pass `--model qwen2.5vl:7b`.

## Usage

```
python run.py "C:\Invoices\August"
```

Options:

- `--model <name>` — use a different Ollama vision model.
- `--export-only` — skip processing and just regenerate `invoices.xlsx` from
  the existing database.

The tool never modifies or deletes files in the invoice folder — it only ever
adds `invoices.xlsx` there.

## Output

- `invoices.db` — SQLite database in the project folder, the source of truth
  for all extracted data.
- `invoices.xlsx` — Excel workbook written into the invoice folder you pass on
  the command line. It has two sheets:
  - **Invoices** — every invoice, sorted by invoice date. Rows that failed
    validation are highlighted yellow, with the reason in the **Flags**
    column (e.g. "ABN fails checksum", "GST doesn't match expected 1/11 of
    total").
  - **Monthly Summary** — per-month totals (count, spend, GST, ex-GST),
    calculated from approved invoices only. The GST column is meant to line
    up with the GST credit figure used on a BAS.

**`invoices.xlsx` is fully regenerated from the database on every run.** Any
manual edits made directly in the spreadsheet will be lost the next time you
run the tool. If a value is wrong, fix it at the source (or in the database)
rather than in the spreadsheet.

If `invoices.xlsx` is open in Excel when the tool tries to save it, close it
and rerun — your extracted data is already safely stored in the database, so
rerunning only regenerates the spreadsheet.

## Known limitations

- Vision models occasionally misread individual digits, especially in ABNs,
  invoice numbers, and dates. The validation checks (ABN checksum, GST
  reconciliation) catch most of these and route them to `needs_review`, but
  they won't catch every possible misread — a flagged invoice is worth an
  actual glance at the source file.
- There's currently no in-tool way to correct a flagged invoice and promote
  it to approved; that has to be done directly against the database for now.
- Single-invoice-per-file only — no line-item extraction, no multi-invoice
  PDFs.
