"""Extracts structured invoice data from a PDF or image using a local Ollama vision model."""

import os
import tempfile
from typing import Optional

import ollama
import pymupdf as fitz
from pydantic import BaseModel

# The model is a config constant so it's easy to swap.
MODEL = "gemma3:12b"

DPI_STANDARD = 300
DPI_FALLBACK = 200  # used for multi-page PDFs if the standard DPI overflows context
MAX_PAGES = 5

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS


class Invoice(BaseModel):
    supplier_name: Optional[str] = None
    supplier_abn: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    subtotal: Optional[float] = None
    gst: Optional[float] = None
    total: Optional[float] = None


PROMPT = (
    "This is an Australian invoice or receipt. Extract the following fields and "
    "return ONLY valid JSON matching this exact structure, no extra text, no "
    "markdown formatting:\n\n"
    '{"supplier_name": string, "supplier_abn": string, "invoice_number": string, '
    '"invoice_date": string, "due_date": string, "subtotal": number, '
    '"gst": number, "total": number}\n\n'
    "Field rules — read carefully:\n"
    "- supplier_name and supplier_abn are the SUPPLIER issuing the invoice, not "
    "the customer being billed. Some invoices print both ABNs — pick the one "
    "next to the supplier's own name and details.\n"
    "- invoice_number is the invoice number exactly as printed.\n"
    "- Printed dates on this invoice are in DD/MM/YYYY format. Convert "
    "invoice_date and due_date to YYYY-MM-DD.\n"
    "- due_date is null if no due date is shown (common on receipts). It may be "
    "labelled 'Due Date', or phrased as 'Payment due', 'Please pay by', or "
    "'Direct debit on <date>'.\n"
    "- subtotal is the amount before GST, but ONLY if it is printed as its own "
    "line on the invoice. If there is no separate subtotal line, use null — do "
    "not calculate one.\n"
    "- gst is the GST amount exactly as printed.\n"
    "- total is the final amount payable (e.g. next to 'Total' or 'Amount Due'), "
    "exactly as printed. It always includes GST.\n"
    "- Copy printed values exactly. Do not perform any arithmetic yourself.\n"
    "- If a field is not visible on the invoice, use null.\n"
)


def _render_pdf_pages(pdf_path: str, out_dir: str, dpi: int, max_pages: int) -> list[str]:
    image_paths = []
    doc = fitz.open(pdf_path)
    try:
        page_count = min(len(doc), max_pages)
        for i in range(page_count):
            pix = doc[i].get_pixmap(dpi=dpi)
            image_path = os.path.join(out_dir, f"page_{i + 1}.png")
            pix.save(image_path)
            image_paths.append(image_path)
    finally:
        doc.close()
    return image_paths


def _call_model(image_paths: list[str], model: str) -> Invoice:
    response = ollama.chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": PROMPT,
                "images": image_paths,
            }
        ],
        format=Invoice.model_json_schema(),
        options={
            "temperature": 0,
            "num_ctx": 8192,
        },
    )
    raw_content = response["message"]["content"]
    return Invoice.model_validate_json(raw_content)


def extract_invoice(file_path: str, model: str = MODEL) -> Invoice:
    """Extracts an Invoice from a PDF or image file. Rendered pages are kept in a
    temp directory and cleaned up before returning."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext in PDF_EXTENSIONS:
        with tempfile.TemporaryDirectory(prefix="invoice_scheduler_") as tmp_dir:
            image_paths = _render_pdf_pages(file_path, tmp_dir, DPI_STANDARD, MAX_PAGES)
            is_multipage = len(image_paths) > 1
            try:
                return _call_model(image_paths, model)
            except ollama.ResponseError as e:
                message = str(e).lower()
                if is_multipage and "context" in message:
                    image_paths = _render_pdf_pages(file_path, tmp_dir, DPI_FALLBACK, MAX_PAGES)
                    return _call_model(image_paths, model)
                raise
    elif ext in IMAGE_EXTENSIONS:
        return _call_model([file_path], model)
    else:
        raise ValueError(f"Unsupported file type: {ext}")
