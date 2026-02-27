"""
tests/test_normalize_preamble.py
=================================
Unit tests for open_holdings_table() and normalize_csv() preamble handling.

Uses only synthetic in-memory data — no real portfolio files are read.
stdlib unittest only; no pytest or other external test dependency required.

Run:
    python -m pytest tests/                      # if pytest is available
    python -m unittest tests.test_normalize_preamble   # stdlib only
"""

import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Synthetic CSV fixtures
# ---------------------------------------------------------------------------

# TD WebBroker-style export: several metadata rows before the holdings table.
_PREAMBLE_CSV = """\
Account Number,12345678
Account Type,TFSA
As of Date,2026-02-24
,
Symbol,Description,Quantity,Average Cost,Price,Book Cost,Market Value,Unrealized $,Unrealized %
AAPL,Apple Inc,10,150.00,190.00,1500.00,1900.00,400.00,26.67
VFV.TO,Vanguard S&P 500 ETF,20,100.00,120.00,2000.00,2400.00,400.00,20.00
"""

# Standard clean export: header is the very first line (no preamble).
_CLEAN_CSV = """\
Symbol,Description,Quantity,Price,Market Value
AAPL,Apple Inc,10,190.00,1900.00
VFV.TO,Vanguard S&P 500 ETF,20,120.00,2400.00
"""

# No recognizable holdings header at all.
_NO_HEADER_CSV = """\
Account Number,12345
Date,2026-02-24
Random,Data
"""

# Header recognised by the "contains Symbol + Market + Description" fallback
# (no "Symbol," prefix but all three keywords are present).
_KEYWORD_MATCH_CSV = """\
Metadata,Row
Extra Info,Here
Description,Symbol,Quantity,Market Value
AAPL,Apple Inc,10,1900.00
"""


def _write_temp(content: str) -> Path:
    """Write content to a NamedTemporaryFile and return its Path."""
    fh = tempfile.NamedTemporaryFile(
        suffix=".csv", delete=False, mode="w", encoding="utf-8"
    )
    fh.write(content)
    fh.close()
    return Path(fh.name)


class TestOpenHoldingsTable(unittest.TestCase):
    """Tests for the open_holdings_table() helper in isolation."""

    def test_preamble_stripped_header_is_first_line(self):
        """After a TD-style preamble, the returned StringIO starts at Symbol,..."""
        from agents.ori_ia.normalize import open_holdings_table

        path = _write_temp(_PREAMBLE_CSV)
        try:
            table = open_holdings_table(path)
            first = table.readline()
            self.assertTrue(
                first.startswith("Symbol,"),
                f"Expected 'Symbol,...' as first line, got: {first!r}",
            )
        finally:
            path.unlink()

    def test_clean_csv_passes_through(self):
        """A CSV with no preamble still works — header is line 1."""
        from agents.ori_ia.normalize import open_holdings_table

        path = _write_temp(_CLEAN_CSV)
        try:
            table = open_holdings_table(path)
            first = table.readline()
            self.assertTrue(first.startswith("Symbol,"))
        finally:
            path.unlink()

    def test_no_header_raises_value_error(self):
        """ValueError is raised when no holdings header can be found."""
        from agents.ori_ia.normalize import open_holdings_table

        path = _write_temp(_NO_HEADER_CSV)
        try:
            with self.assertRaises(ValueError) as ctx:
                open_holdings_table(path)
            self.assertIn("Holdings header not found", str(ctx.exception))
            self.assertIn(path.name, str(ctx.exception))
        finally:
            path.unlink()

    def test_keyword_fallback_match(self):
        """Header detected via keyword fallback (Symbol+Market+Description present)."""
        from agents.ori_ia.normalize import open_holdings_table

        path = _write_temp(_KEYWORD_MATCH_CSV)
        try:
            table = open_holdings_table(path)
            first = table.readline()
            # Header line contains "Description" and "Symbol"
            self.assertIn("Description", first)
            self.assertIn("Symbol", first)
        finally:
            path.unlink()


class TestNormalizeCsvPreamble(unittest.TestCase):
    """Tests for normalize_csv() end-to-end with preamble inputs."""

    def test_preamble_csv_returns_2_rows(self):
        """normalize_csv skips preamble metadata and returns exactly 2 data rows."""
        from agents.ori_ia.normalize import normalize_csv

        path = _write_temp(_PREAMBLE_CSV)
        try:
            rows, detected, unmapped = normalize_csv(path)
            self.assertEqual(len(rows), 2)
        finally:
            path.unlink()

    def test_symbol_mapped_correctly(self):
        """'Symbol' column maps to canonical 'symbol' field for both rows."""
        from agents.ori_ia.normalize import normalize_csv

        path = _write_temp(_PREAMBLE_CSV)
        try:
            rows, _, _ = normalize_csv(path)
            self.assertEqual(rows[0]["symbol"], "AAPL")
            self.assertEqual(rows[1]["symbol"], "VFV.TO")
        finally:
            path.unlink()

    def test_market_value_parsed_to_float(self):
        """'Market Value' column is parsed to float in the canonical field."""
        from agents.ori_ia.normalize import normalize_csv

        path = _write_temp(_PREAMBLE_CSV)
        try:
            rows, _, _ = normalize_csv(path)
            self.assertAlmostEqual(rows[0]["market_value"], 1900.0)
            self.assertAlmostEqual(rows[1]["market_value"], 2400.0)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
