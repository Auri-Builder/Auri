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
import io
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


def open_holdings_table(csv_path: Path) -> io.StringIO:
    """
    Read a broker CSV and return a StringIO of the holdings table only.

    Many brokers (e.g. TD WebBroker) prepend metadata rows before the actual
    holdings table. This helper scans past those rows and returns a file-like
    object containing only the header line and the data rows that follow it.

    Detection: the header line must satisfy at least one of:
      1. Starts with "Symbol," after stripping leading whitespace (exact prefix).
      2. Contains all three words: "Symbol", "Market", "Description".

    The returned StringIO is positioned at the beginning (ready to read).

    Args:
        csv_path: path to the CSV file (caller is responsible for sandbox safety)

    Returns:
        io.StringIO containing header + data rows.

    Raises:
        ValueError: if no holdings header line is found in the file.
    """
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        header_line: str | None = None
        for raw_line in fh:
            stripped = raw_line.lstrip()
            if stripped.startswith("Symbol,") or all(
                word in stripped for word in ("Symbol", "Market", "Description")
            ):
                header_line = raw_line
                break

        if header_line is None:
            raise ValueError(f"Holdings header not found in {csv_path.name}")

        # Slurp the remaining data rows while still inside the open file context.
        remaining = fh.read()

    return io.StringIO(header_line + remaining)


def normalize_csv(
    csv_path: Path,
) -> tuple[list[dict], list[str], list[str]]:
    """
    Read and normalize a portfolio CSV to the ORI_IA canonical schema.

    Delegates preamble detection to open_holdings_table(), which returns a
    StringIO of the holdings table (header + data rows). The rest of this
    function only deals with parsing canonical fields — no file-format concerns.

    Args:
        csv_path: resolved, sandbox-validated path to the CSV file
                  (caller is responsible for path safety)

    Returns:
        rows:             list of canonical dicts — one per holding row.
                          Each dict has exactly the CANONICAL_FIELDS keys.
                          Unmapped/absent fields are None; numeric fields
                          are parsed to float (or None if missing/unparseable).
        detected_fields:  canonical field names successfully mapped from headers.
        unmapped_columns: CSV column names that did not match COLUMN_MAP.

    Raises:
        ValueError: if no holdings header is found (propagated from
                    open_holdings_table) or if the table has no fieldnames.
    """
    rows: list[dict] = []

    # open_holdings_table skips any broker preamble and positions the returned
    # StringIO at the holdings header line. May raise ValueError.
    table = open_holdings_table(csv_path)
    reader = csv.DictReader(table)

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
