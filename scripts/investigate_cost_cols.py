"""
D2a Investigation Helper — Cost Basis Column Audit
===================================================
Prints only the header columns that contain "book" or "cost" (case-insensitive)
from every portfolio CSV in data/portfolio/, along with their column index.

No row data is read or printed. This is a read-only diagnostic tool.

Usage (from repo root):
    python scripts/investigate_cost_cols.py
"""

import csv
import io
import sys
from pathlib import Path

# Ensure repo root is on sys.path so we can import project modules.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.ori_ia.normalize import open_holdings_table  # noqa: E402
from agents.ori_ia.schema import COLUMN_MAP              # noqa: E402

PORTFOLIO_DIR = PROJECT_ROOT / "data" / "portfolio"


def audit_file(csv_path: Path) -> None:
    print(f"\n── {csv_path.name} ──")
    try:
        table: io.StringIO = open_holdings_table(csv_path)
        reader = csv.DictReader(table)
        headers = list(reader.fieldnames or [])
    except Exception as exc:
        print(f"  ERROR reading file: {exc}")
        return

    if not headers:
        print("  No headers found.")
        return

    target_headers = [
        (i, h) for i, h in enumerate(headers)
        if "book" in h.lower() or "cost" in h.lower()
    ]

    if not target_headers:
        print("  No 'book'/'cost' columns found.")
        return

    for idx, header in target_headers:
        lookup = header.strip().lower()
        canonical = COLUMN_MAP.get(lookup, "<not in COLUMN_MAP>")
        note = "(intentionally dropped)" if canonical is None else f"→ canonical: {canonical!r}"
        print(f"  [{idx:>2}] {header!r:30s}  {note}")


def main() -> None:
    csvs = sorted(PORTFOLIO_DIR.glob("*.csv"))
    if not csvs:
        print(f"No CSV files found in {PORTFOLIO_DIR}")
        return

    print("Cost/book column audit across portfolio CSVs")
    print("=" * 60)
    for path in csvs:
        audit_file(path)
    print()


if __name__ == "__main__":
    main()
