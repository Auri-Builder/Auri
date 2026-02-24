"""
ORI_IA CSV Normalization Module
================================
Reads a portfolio CSV from a caller-validated path and normalizes every
row to the ORI_IA canonical schema (14 fields, see schema.py).

Design principles:
  - Tolerant of column name variations (matched via COLUMN_MAP, case-insensitive)
  - Tolerant of missing optional fields (default to None)
  - Robust numeric parsing: strips currency symbols, commas, parentheses
  - No path resolution or sandbox logic here — the caller (job_runner) is
    responsible for validating and confining the path before passing it in.
  - No side effects: pure read, returns data structures.
"""

import csv
import logging
from pathlib import Path

from agents.ori_ia.schema import CANONICAL_FIELDS, COLUMN_MAP, NUMERIC_FIELDS

logger = logging.getLogger(__name__)


def detect_column_mapping(
    headers: list[str],
) -> tuple[dict[str, str], list[str]]:
    """
    Map CSV header names to canonical ORI_IA field names.

    Args:
        headers: raw list of CSV column names (as read by csv.DictReader)

    Returns:
        mapping:  {csv_col_name -> canonical_field_name} for recognized columns
        unmapped: list of CSV column names that could not be mapped

    Matching is case-insensitive and whitespace-stripped.
    If two source columns resolve to the same canonical field, the first one
    wins and the duplicate is reported as unmapped.
    """
    mapping: dict[str, str] = {}
    unmapped: list[str] = []
    claimed: set[str] = set()  # canonical fields already assigned to a source column

    for col in headers:
        lookup_key = col.strip().lower()
        canonical = COLUMN_MAP.get(lookup_key)

        if canonical is None:
            # Header not found in mapping table
            unmapped.append(col)
            logger.debug("Column %r not in COLUMN_MAP — will be dropped", col)

        elif canonical in claimed:
            # Two CSV columns map to the same canonical field — keep first, drop second
            unmapped.append(col)
            logger.warning(
                "Duplicate mapping: %r also maps to '%s' (already claimed) — dropped",
                col, canonical,
            )

        else:
            mapping[col] = canonical
            claimed.add(canonical)
            logger.debug("Column %r → '%s'", col, canonical)

    if unmapped:
        logger.info("Unmapped/dropped CSV columns: %s", unmapped)

    return mapping, unmapped


def parse_numeric(value: str | None) -> float | None:
    """
    Parse a numeric string that may include:
      - Currency symbols:  $  £  €
      - Percentage sign:   %
      - Thousands commas:  1,234.56
      - Parentheses for negatives: (1,234.56) → -1234.56
      - Leading/trailing whitespace

    Returns None for empty, missing, or non-parseable values.
    """
    if value is None:
        return None

    cleaned = value.strip()

    # Treat explicit empty/missing markers as None
    if not cleaned or cleaned in {"-", "--", "n/a", "na", "N/A", "NA", ""}:
        return None

    # Parentheses denote negative values in some export formats
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]

    # Strip all non-numeric characters except the decimal point and minus sign
    for ch in ("$", "£", "€", "%", ",", " "):
        cleaned = cleaned.replace(ch, "")

    try:
        result = float(cleaned)
        return -result if negative else result
    except ValueError:
        logger.debug("Could not parse numeric value: %r", value)
        return None


def normalize_csv(
    csv_path: Path,
) -> tuple[list[dict], list[str], list[str]]:
    """
    Read and normalize a portfolio CSV to the ORI_IA canonical schema.

    Args:
        csv_path: resolved, sandbox-validated path to the CSV file
                  (caller is responsible for path safety)

    Returns:
        rows:              list of canonical dicts — one per holding row.
                           Each dict has exactly the CANONICAL_FIELDS keys.
                           Unmapped/absent fields are None; numeric fields
                           are parsed to float (or None if missing/unparseable).
        detected_fields:   canonical field names that were successfully mapped
                           from this CSV's headers.
        unmapped_columns:  CSV column names that did not match COLUMN_MAP.

    Opens with utf-8-sig encoding to handle BOM markers that some broker
    export tools include at the start of the file.
    """
    rows: list[dict] = []

    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)

        if not reader.fieldnames:
            raise ValueError(f"CSV appears empty or has no header row: {csv_path.name}")

        col_mapping, unmapped_columns = detect_column_mapping(list(reader.fieldnames))
        detected_fields = list(set(col_mapping.values()))

        for raw_row in reader:
            # Start from a blank canonical row so every key is always present
            canonical_row: dict = {field: None for field in CANONICAL_FIELDS}

            for csv_col, canonical_field in col_mapping.items():
                raw_value = raw_row.get(csv_col)

                if canonical_field in NUMERIC_FIELDS:
                    canonical_row[canonical_field] = parse_numeric(raw_value)
                else:
                    # String field: strip and coerce empty string to None
                    stripped = (raw_value or "").strip()
                    canonical_row[canonical_field] = stripped or None

            rows.append(canonical_row)

    logger.info(
        "Normalized %d row(s) from '%s' | %d canonical fields detected | "
        "%d column(s) unmapped",
        len(rows),
        csv_path.name,
        len(detected_fields),
        len(unmapped_columns),
    )

    return rows, detected_fields, unmapped_columns
