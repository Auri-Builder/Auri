"""
agents/ori_ia/extract.py

Shared utility for stripping broker preamble from raw CSV exports.

Imported by:
  pages/wizard.py  — validates before writing to data/portfolio/
  pages/health.py  — validates existing files non-destructively

Stdlib only. No Streamlit, pandas, or pyyaml dependencies.
"""

import csv as _csv
import io as _io
from pathlib import Path


def extract_holdings_table(raw_path: Path, cleaned_path: Path) -> None:
    """
    Strip broker preamble from a raw CSV export and write a clean CSV that
    starts at the holdings header row.

    Detection criteria (all must match, case-insensitive, via CSV-aware parsing):
      - at least one column containing "symbol"
      - at least one column equal to "quantity" or "shares"
      - the joined column string contains one of:
        "market value", "marketvalue", "value", "mv"
      - at least 8 columns in the row

    Reads with utf-8-sig to handle BOM from broker exports (e.g. TD Wealth).
    Writes utf-8 (no BOM).
    Raises ValueError if no matching header row is found.
    """
    lines = raw_path.read_text(encoding="utf-8-sig").splitlines()
    header_index = None

    for i, line in enumerate(lines):
        # Use csv.reader on a single line so quoted commas are handled correctly
        # and we get accurate column counts.
        try:
            cols = next(_csv.reader(_io.StringIO(line)))
        except StopIteration:
            continue

        lower_cols = [c.strip().lower() for c in cols]
        joined = " ".join(lower_cols)

        has_symbol = any("symbol" in c for c in lower_cols)
        has_qty    = any(c in ("quantity", "shares") for c in lower_cols)
        has_mv     = any(
            v in joined
            for v in ("market value", "marketvalue", "value", "mv")
        )

        if has_symbol and has_qty and has_mv and len(cols) >= 8:
            header_index = i
            break

    if header_index is None:
        raise ValueError(
            "Could not detect holdings header row. "
            "Expected a row with: symbol, quantity/shares, market value, and ≥8 columns. "
            "Ensure you exported the 'Holdings' view (not activity or summary)."
        )

    # Write cleaned file: header row onwards, no preamble.
    cleaned_path.write_text("\n".join(lines[header_index:]), encoding="utf-8")
