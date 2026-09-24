"""CLI: process a single invoice file through the full pipeline.
Usage: python scripts/process_invoice_cli.py path/to/invoice.pdf
"""
from __future__ import annotations

import sys

from backend.db.base import SessionLocal
from backend.services.pipeline_service import process_invoice_file


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/process_invoice_cli.py <invoice_path>")
        sys.exit(1)
    db = SessionLocal()
    invoice = process_invoice_file(db, sys.argv[1])
    print(f"Invoice {invoice.id}: status={invoice.status} confidence={invoice.confidence_score}")
    for f in invoice.findings:
        print(f"  [{f.severity}] {f.code}: {f.message}")
    db.close()


if __name__ == "__main__":
    main()
