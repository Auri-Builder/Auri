"""
Unit tests for agents.ori_ia.enrich — symbol reference loading and row enrichment.

All tests use synthetic data only. No real portfolio files are read.
"""
import tempfile
import textwrap
import unittest
from pathlib import Path

from agents.ori_ia.enrich import enrich_rows, load_symbol_ref

_VALID_YAML = textwrap.dedent("""\
    symbols:
      VFV:  {sector: "Equities - US", asset_class: "ETF"}
      ENB:  {sector: "Energy",        asset_class: "Equity"}
""")


class TestLoadSymbolRef(unittest.TestCase):
    def test_returns_empty_if_file_absent(self):
        missing = Path("/tmp/does_not_exist_auri_test.yaml")
        result = load_symbol_ref(missing)
        self.assertEqual(result, {})

    def test_parses_valid_yaml_keys_are_uppercase(self):
        # Keys in the YAML file may be any case; load_symbol_ref normalises them
        # to uppercase so that lookups are always case-insensitive.
        yaml_mixed_case = textwrap.dedent("""\
            symbols:
              vfv:  {sector: "Equities - US", asset_class: "ETF"}
              Enb:  {sector: "Energy",        asset_class: "Equity"}
        """)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_mixed_case)
            tmp_path = Path(f.name)

        result = load_symbol_ref(tmp_path)
        tmp_path.unlink(missing_ok=True)

        # Keys are stored uppercase regardless of what the YAML had.
        self.assertIn("VFV", result)
        self.assertNotIn("vfv", result)
        self.assertEqual(result["VFV"]["sector"], "Equities - US")
        self.assertEqual(result["ENB"]["asset_class"], "Equity")

    def test_raises_on_missing_symbols_key(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("not_symbols:\n  FOO: bar\n")
            tmp_path = Path(f.name)

        with self.assertRaises(ValueError):
            load_symbol_ref(tmp_path)
        tmp_path.unlink(missing_ok=True)


class TestEnrichRows(unittest.TestCase):
    def _make_row(self, symbol, sector=None, asset_class=None):
        return {
            "symbol": symbol,
            "sector": sector,
            "asset_class": asset_class,
            "market_value": 1000.0,
        }

    def test_fills_none_sector(self):
        rows = [self._make_row("VFV")]
        ref = {"VFV": {"sector": "Equities - US", "asset_class": "ETF"}}
        enrich_rows(rows, ref)
        self.assertEqual(rows[0]["sector"], "Equities - US")

    def test_fills_none_asset_class(self):
        rows = [self._make_row("ENB")]
        ref = {"ENB": {"sector": "Energy", "asset_class": "Equity"}}
        enrich_rows(rows, ref)
        self.assertEqual(rows[0]["asset_class"], "Equity")

    def test_does_not_overwrite_existing_sector(self):
        rows = [self._make_row("VFV", sector="Technology")]
        ref = {"VFV": {"sector": "Equities - US", "asset_class": "ETF"}}
        enrich_rows(rows, ref)
        # CSV-supplied value must survive
        self.assertEqual(rows[0]["sector"], "Technology")

    def test_skips_unknown_symbol_without_error(self):
        rows = [self._make_row("UNKNOWN_XYZ")]
        ref = {"VFV": {"sector": "Equities - US", "asset_class": "ETF"}}
        enrich_rows(rows, ref)  # should not raise
        self.assertIsNone(rows[0]["sector"])

    def test_no_op_on_empty_ref(self):
        rows = [self._make_row("VFV")]
        enrich_rows(rows, {})
        self.assertIsNone(rows[0]["sector"])

    def test_skips_row_with_no_symbol(self):
        rows = [{"symbol": None, "sector": None, "asset_class": None}]
        ref = {"VFV": {"sector": "Equities - US", "asset_class": "ETF"}}
        enrich_rows(rows, ref)  # should not raise
        self.assertIsNone(rows[0]["sector"])

    def test_lookup_is_case_insensitive(self):
        # Row has lowercase symbol; ref was loaded with uppercase keys.
        # enrich_rows must normalize before lookup so this still matches.
        rows = [self._make_row("vfv")]
        ref = {"VFV": {"sector": "Equities - US", "asset_class": "ETF"}}
        enrich_rows(rows, ref)
        self.assertEqual(rows[0]["sector"], "Equities - US")


if __name__ == "__main__":
    unittest.main()
