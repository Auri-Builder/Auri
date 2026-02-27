"""
tests/test_cost_basis_mapping.py
=================================
Unit tests for the D2a cost-basis duplicate-mapping fix.

Background
----------
TD WebBroker exports both:
  "Average Cost"  [col 4]  — per-share unit cost  (e.g. 13.3616)
  "Book Cost"     [col 6]  — total position cost   (e.g. 4823.52)

Both map to the canonical cost_basis field.  Before the D2a fix,
"Average Cost" won (appears first in the header) and "Book Cost" triggered a
duplicate-mapping WARNING.  The canonical cost_basis then held the per-share
unit cost — semantically wrong.

After the fix:
  "average cost" → None  (intentionally dropped in COLUMN_MAP)
  "book cost"    → "cost_basis"  (wins cleanly; holds total CAD book cost)

Tests
-----
  TestDetectColumnMappingCostBasis   — low-level detect_column_mapping behaviour
  TestNormalizeCsvCostBasis          — end-to-end normalize_csv with temp CSVs
  TestColumnMapConstants             — static assertions on COLUMN_MAP entries

Run:
    python -m unittest tests.test_cost_basis_mapping   (stdlib)
    python -m pytest tests/                            (if pytest available)
"""

import logging
import tempfile
import unittest
from pathlib import Path


# ---------------------------------------------------------------------------
# CSV fixtures
# ---------------------------------------------------------------------------

# TD WebBroker pattern: "Average Cost" appears before "Book Cost".
_TD_CSV = """\
As of Date,2026-02-24
Account,TD Wealth - 7BX000X
,
Symbol,Market,Description,Quantity,Average Cost,Price,Book Cost,Market Value,Unrealized $,Unrealized %,% of Positions,Loan Value,Change Today $,Change Today %
AAPL,US,Apple Inc,10,150.00,190.00,1500.00,1900.00,400.00,26.67,10.00,,0.50,0.26
VFV.TO,CA,Vanguard S&P 500 ETF,20,100.00,120.00,2000.00,2400.00,400.00,20.00,13.00,,-0.10,-0.08
"""

# Export that only provides "Book Cost" (no "Average Cost" column).
_BOOK_COST_ONLY_CSV = """\
Symbol,Description,Quantity,Price,Book Cost,Market Value
AAPL,Apple Inc,10,190.00,1500.00,1900.00
"""

# Export that only provides "avg cost" (no "Book Cost" / "Average Cost").
# This covers non-TD brokers that expose only a per-share average.
_AVG_COST_ONLY_CSV = """\
Symbol,Description,Quantity,Price,Avg Cost,Market Value
AAPL,Apple Inc,10,190.00,150.00,1900.00
"""

# Export with "Average Cost" but NO "Book Cost" — canonical cost_basis should
# be None (the column is intentionally dropped, nothing else provides it).
_AVERAGE_COST_ONLY_CSV = """\
Symbol,Description,Quantity,Price,Average Cost,Market Value
AAPL,Apple Inc,10,190.00,150.00,1900.00
"""


def _write_temp(content: str) -> Path:
    fh = tempfile.NamedTemporaryFile(
        suffix=".csv", delete=False, mode="w", encoding="utf-8"
    )
    fh.write(content)
    fh.close()
    return Path(fh.name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDetectColumnMappingCostBasis(unittest.TestCase):
    """
    Low-level tests for detect_column_mapping() with cost-basis header variants.
    """

    def test_td_pattern_book_cost_wins(self):
        """With both 'Average Cost' and 'Book Cost', 'Book Cost' maps to cost_basis."""
        from agents.ori_ia.normalize import detect_column_mapping

        headers = ["Symbol", "Average Cost", "Price", "Book Cost", "Market Value"]
        mapping, unmapped = detect_column_mapping(headers)

        self.assertEqual(mapping.get("Book Cost"), "cost_basis",
                         "'Book Cost' must map to cost_basis")
        self.assertNotIn("Average Cost", mapping,
                         "'Average Cost' must not be in mapping (intentionally dropped)")

    def test_td_pattern_average_cost_in_unmapped(self):
        """'Average Cost' ends up in the unmapped list (intentionally dropped, not unknown)."""
        from agents.ori_ia.normalize import detect_column_mapping

        headers = ["Symbol", "Average Cost", "Price", "Book Cost", "Market Value"]
        _, unmapped = detect_column_mapping(headers)

        self.assertIn("Average Cost", unmapped,
                      "'Average Cost' should appear in unmapped (intentionally dropped)")

    def test_td_pattern_no_duplicate_warning(self):
        """No duplicate-mapping WARNING is emitted when both 'Average Cost' and 'Book Cost' are present."""
        from agents.ori_ia.normalize import detect_column_mapping

        headers = ["Symbol", "Average Cost", "Price", "Book Cost", "Market Value"]

        with self.assertLogs("agents.ori_ia.normalize", level="WARNING") as cm:
            detect_column_mapping(headers)
            # Force at least one record so assertLogs doesn't blow up (we just need
            # to verify none of them is a duplicate-mapping warning).
            logging.getLogger("agents.ori_ia.normalize").warning("_sentinel_")

        warnings = [m for m in cm.output if "Duplicate mapping" in m]
        self.assertEqual(warnings, [],
                         f"No 'Duplicate mapping' warning expected; got: {warnings}")

    def test_book_cost_only_maps_normally(self):
        """When only 'Book Cost' is present, it maps cleanly to cost_basis."""
        from agents.ori_ia.normalize import detect_column_mapping

        headers = ["Symbol", "Price", "Book Cost", "Market Value"]
        mapping, unmapped = detect_column_mapping(headers)

        self.assertEqual(mapping.get("Book Cost"), "cost_basis")
        self.assertNotIn("Book Cost", unmapped)

    def test_avg_cost_maps_to_cost_basis(self):
        """'avg cost' (non-TD variant) still maps to cost_basis."""
        from agents.ori_ia.normalize import detect_column_mapping

        headers = ["Symbol", "Avg Cost", "Market Value"]
        mapping, _ = detect_column_mapping(headers)

        self.assertEqual(mapping.get("Avg Cost"), "cost_basis",
                         "'Avg Cost' must still map to cost_basis for non-TD exports")

    def test_average_cost_alone_is_dropped(self):
        """'Average Cost' with no 'Book Cost' is intentionally dropped → cost_basis unmapped."""
        from agents.ori_ia.normalize import detect_column_mapping

        headers = ["Symbol", "Average Cost", "Market Value"]
        mapping, unmapped = detect_column_mapping(headers)

        self.assertNotIn("Average Cost", mapping)
        self.assertIn("Average Cost", unmapped)
        self.assertNotIn("cost_basis", mapping.values())


class TestNormalizeCsvCostBasis(unittest.TestCase):
    """
    End-to-end normalize_csv() tests with temporary CSV files.
    """

    def test_td_csv_cost_basis_is_total_book_cost(self):
        """
        For a TD-style export, canonical cost_basis holds 'Book Cost' (total),
        not 'Average Cost' (per-share).
        """
        from agents.ori_ia.normalize import normalize_csv

        path = _write_temp(_TD_CSV)
        try:
            rows, _, _ = normalize_csv(path)
            # Row 0: Book Cost = 1500.00, Average Cost = 150.00
            # The canonical cost_basis must be the total (1500.00).
            self.assertAlmostEqual(rows[0]["cost_basis"], 1500.0,
                                   msg="cost_basis should be total Book Cost, not per-share Average Cost")
            self.assertAlmostEqual(rows[1]["cost_basis"], 2000.0)
        finally:
            path.unlink()

    def test_td_csv_average_cost_in_unmapped(self):
        """'Average Cost' appears in the unmapped list for a TD CSV (intentionally dropped)."""
        from agents.ori_ia.normalize import normalize_csv

        path = _write_temp(_TD_CSV)
        try:
            _, _, unmapped = normalize_csv(path)
            self.assertIn("Average Cost", unmapped)
        finally:
            path.unlink()

    def test_td_csv_no_duplicate_warning(self):
        """Calling normalize_csv on a TD export emits no duplicate-mapping WARNING."""
        from agents.ori_ia.normalize import normalize_csv

        path = _write_temp(_TD_CSV)
        try:
            with self.assertLogs("agents.ori_ia.normalize", level="WARNING") as cm:
                normalize_csv(path)
                logging.getLogger("agents.ori_ia.normalize").warning("_sentinel_")
            dup_warnings = [m for m in cm.output if "Duplicate mapping" in m]
            self.assertEqual(dup_warnings, [],
                             f"Unexpected duplicate-mapping warnings: {dup_warnings}")
        finally:
            path.unlink()

    def test_book_cost_only_csv_maps_correctly(self):
        """CSV with only 'Book Cost' normalizes cost_basis as total book cost."""
        from agents.ori_ia.normalize import normalize_csv

        path = _write_temp(_BOOK_COST_ONLY_CSV)
        try:
            rows, _, _ = normalize_csv(path)
            self.assertAlmostEqual(rows[0]["cost_basis"], 1500.0)
        finally:
            path.unlink()

    def test_avg_cost_only_csv_maps_correctly(self):
        """CSV with only 'Avg Cost' normalizes cost_basis (non-TD per-share fallback)."""
        from agents.ori_ia.normalize import normalize_csv

        path = _write_temp(_AVG_COST_ONLY_CSV)
        try:
            rows, _, _ = normalize_csv(path)
            self.assertAlmostEqual(rows[0]["cost_basis"], 150.0)
        finally:
            path.unlink()

    def test_average_cost_only_csv_cost_basis_is_none(self):
        """
        CSV with only 'Average Cost' (and no 'Book Cost' / 'Avg Cost') yields
        cost_basis=None — the column is intentionally dropped, nothing else provides it.
        """
        from agents.ori_ia.normalize import normalize_csv

        path = _write_temp(_AVERAGE_COST_ONLY_CSV)
        try:
            rows, detected_fields, _ = normalize_csv(path)
            self.assertIsNone(rows[0]["cost_basis"],
                              "cost_basis must be None when only 'Average Cost' is present")
            self.assertNotIn("cost_basis", detected_fields,
                             "cost_basis should not appear in detected_fields")
        finally:
            path.unlink()

    def test_td_csv_other_canonical_fields_unaffected(self):
        """The D2a fix does not regress other canonical field mappings."""
        from agents.ori_ia.normalize import normalize_csv

        path = _write_temp(_TD_CSV)
        try:
            rows, _, _ = normalize_csv(path)
            row = rows[0]
            self.assertEqual(row["symbol"], "AAPL")
            self.assertEqual(row["security_name"], "Apple Inc")
            self.assertAlmostEqual(row["market_value"], 1900.0)
            self.assertAlmostEqual(row["price"], 190.0)
            self.assertAlmostEqual(row["quantity"], 10.0)
            self.assertAlmostEqual(row["unrealized_gain"], 400.0)
        finally:
            path.unlink()


class TestColumnMapConstants(unittest.TestCase):
    """
    Static assertions on COLUMN_MAP entries relevant to the D2a fix.
    These tests protect the fix from being accidentally reverted.
    """

    def test_average_cost_is_intentionally_dropped(self):
        """'average cost' must map to None (intentionally dropped) in COLUMN_MAP."""
        from agents.ori_ia.schema import COLUMN_MAP

        self.assertIn("average cost", COLUMN_MAP,
                      "'average cost' must be present in COLUMN_MAP")
        self.assertIsNone(COLUMN_MAP["average cost"],
                          "'average cost' must map to None (intentionally dropped), "
                          "not to a canonical field")

    def test_book_cost_maps_to_cost_basis(self):
        """'book cost' must map to cost_basis."""
        from agents.ori_ia.schema import COLUMN_MAP

        self.assertEqual(COLUMN_MAP.get("book cost"), "cost_basis")

    def test_avg_cost_maps_to_cost_basis(self):
        """'avg cost' must still map to cost_basis (non-TD fallback)."""
        from agents.ori_ia.schema import COLUMN_MAP

        self.assertEqual(COLUMN_MAP.get("avg cost"), "cost_basis")

    def test_average_cost_and_book_cost_are_distinct_keys(self):
        """'average cost' and 'book cost' are separate keys in COLUMN_MAP."""
        from agents.ori_ia.schema import COLUMN_MAP

        self.assertIn("average cost", COLUMN_MAP)
        self.assertIn("book cost", COLUMN_MAP)
        self.assertNotEqual(COLUMN_MAP["average cost"], COLUMN_MAP["book cost"],
                            "They must resolve differently after the D2a fix")


if __name__ == "__main__":
    unittest.main()
