"""Validation rules for extracted invoices.

`validate_invoice` takes anything with the right attributes (a pydantic
Invoice, a SimpleNamespace, etc.) and returns a list of human-readable flag
strings. Any flag means the invoice should be routed to 'needs_review'.
"""

from datetime import date
from typing import Optional

from storage import normalise_abn

ABN_WEIGHTS = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]


def abn_checksum_valid(abn: Optional[str]) -> bool:
    """Australian Business Number checksum (ATO algorithm)."""
    digits = normalise_abn(abn)
    if not digits or len(digits) != 11:
        return False

    values = [int(d) for d in digits]
    values[0] -= 1
    total = sum(v * w for v, w in zip(values, ABN_WEIGHTS))
    return total % 89 == 0


def _is_valid_iso_date(value: Optional[str]) -> bool:
    if not value:
        return False
    try:
        date.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def validate_invoice(invoice) -> list[str]:
    flags = []

    supplier_name = getattr(invoice, "supplier_name", None)
    supplier_abn = getattr(invoice, "supplier_abn", None)
    invoice_number = getattr(invoice, "invoice_number", None)
    invoice_date = getattr(invoice, "invoice_date", None)
    due_date = getattr(invoice, "due_date", None)
    subtotal = getattr(invoice, "subtotal", None)
    gst = getattr(invoice, "gst", None)
    total = getattr(invoice, "total", None)

    if not supplier_name:
        flags.append("Missing supplier name")
    if not invoice_number:
        flags.append("Missing invoice number")
    if total is None:
        flags.append("Missing total")

    if not supplier_abn:
        flags.append("Missing ABN")
    elif not abn_checksum_valid(supplier_abn):
        flags.append(f"ABN fails checksum: {supplier_abn}")

    if gst is not None and total is not None:
        expected_gst = round(total / 11, 2)
        if abs(expected_gst - gst) > 0.05:
            flags.append(
                f"GST ({gst}) doesn't match expected 1/11 of total ({expected_gst})"
            )
        if gst > total:
            flags.append(f"GST ({gst}) is greater than total ({total})")

    if subtotal is not None and gst is not None and total is not None:
        if abs((subtotal + gst) - total) > 0.02:
            flags.append(
                f"Subtotal ({subtotal}) + GST ({gst}) = {round(subtotal + gst, 2)}, "
                f"doesn't match total ({total})"
            )

    if invoice_date is not None and not _is_valid_iso_date(invoice_date):
        flags.append(f"Invoice date '{invoice_date}' is not a valid ISO date")

    if due_date is not None:
        if not _is_valid_iso_date(due_date):
            flags.append(f"Due date '{due_date}' is not a valid ISO date")
        elif _is_valid_iso_date(invoice_date) and due_date < invoice_date:
            flags.append(
                f"Due date ({due_date}) is before invoice date ({invoice_date}) "
                f"— possible day/month swap"
            )

    return flags


if __name__ == "__main__":
    from types import SimpleNamespace

    def inv(**kwargs):
        defaults = dict(
            supplier_name="Yo Media Australia Pty Ltd",
            supplier_abn="72674603751",
            invoice_number="INV-11220",
            invoice_date="2026-08-01",
            due_date="2026-08-08",
            subtotal=397.27,
            gst=39.73,
            total=437.00,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    passed = 0
    failed = 0

    def check(name, condition):
        global passed, failed
        if condition:
            passed += 1
            print(f"PASS: {name}")
        else:
            failed += 1
            print(f"FAIL: {name}")

    # --- ABN checksum ---
    check("valid ABN (Yo Media)", abn_checksum_valid("72674603751"))
    check("valid ABN (Vodafone)", abn_checksum_valid("76096304620"))
    check("valid ABN (Washed For Cars)", abn_checksum_valid("49681259423"))
    check("valid ABN with spaces", abn_checksum_valid("72 674 603 751"))
    check("invalid ABN (digit swap)", not abn_checksum_valid("72674603741"))
    check("invalid ABN (wrong length)", not abn_checksum_valid("1234567890"))
    check("invalid ABN (None)", not abn_checksum_valid(None))

    # --- clean invoice: no flags ---
    check("clean invoice has no flags", validate_invoice(inv()) == [])

    # --- missing fields ---
    check("missing supplier flagged", "Missing supplier name" in validate_invoice(inv(supplier_name=None)))
    check("missing invoice number flagged", "Missing invoice number" in validate_invoice(inv(invoice_number=None)))
    check("missing total flagged", "Missing total" in validate_invoice(inv(total=None)))
    check("missing ABN flagged", "Missing ABN" in validate_invoice(inv(supplier_abn=None)))

    # --- ABN checksum flag ---
    flags = validate_invoice(inv(supplier_abn="72674603741"))
    check("bad ABN checksum flagged", any("checksum" in f for f in flags))

    # --- GST reconciliation ---
    flags = validate_invoice(inv(gst=39.73, total=437.00))
    check("correct GST (1/11 of total) has no GST flag", not any("GST" in f for f in flags))
    flags = validate_invoice(inv(gst=10.00, total=437.00))
    check("wrong GST flagged", any("doesn't match expected 1/11" in f for f in flags))
    flags = validate_invoice(inv(gst=500.00, total=437.00))
    check("GST greater than total flagged", any("greater than total" in f for f in flags))

    # --- subtotal + gst = total ---
    flags = validate_invoice(inv(subtotal=397.27, gst=39.73, total=437.00))
    check("subtotal+gst=total has no arithmetic flag", not any("doesn't match total" in f for f in flags))
    flags = validate_invoice(inv(subtotal=300.00, gst=39.73, total=437.00))
    check("subtotal+gst!=total flagged", any("doesn't match total" in f for f in flags))

    # --- dates ---
    flags = validate_invoice(inv(invoice_date="18/08/2026"))
    check("non-ISO date flagged", any("not a valid ISO date" in f for f in flags))
    flags = validate_invoice(inv(invoice_date="2026-08-08", due_date="2026-08-01"))
    check("due date before invoice date flagged", any("possible day/month swap" in f for f in flags))
    flags = validate_invoice(inv(due_date=None))
    check("missing due date is NOT flagged", not any("Due date" in f for f in flags))

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
