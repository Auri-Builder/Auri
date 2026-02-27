"""
tests/test_positions_summary.py
================================
Unit tests for analytics.compute_positions_summary().

Uses only synthetic in-memory data — no real portfolio files are read.
stdlib unittest only; no pytest or other external test dependency required.

Run:
    python -m pytest tests/test_positions_summary.py -v
    python -m unittest tests.test_positions_summary
"""

import unittest

from agents.ori_ia.analytics import compute_positions_summary


def _row(
    symbol=None,
    security_name=None,
    market_value=1000.0,
    account_type=None,
    account_id=None,
    institution=None,
    currency="CAD",
    sector=None,
    asset_class=None,
):
    return {
        "symbol":        symbol,
        "security_name": security_name,
        "market_value":  market_value,
        "account_type":  account_type,
        "account_id":    account_id,
        "institution":   institution,
        "currency":      currency,
        "sector":        sector,
        "asset_class":   asset_class,
    }


class TestComputePositionsSummaryBasic(unittest.TestCase):

    def test_returns_empty_when_total_mv_is_zero(self):
        rows = [_row(symbol="AAPL", market_value=1000.0)]
        result = compute_positions_summary(rows, total_mv=0)
        self.assertEqual(result, [])

    def test_single_position_weight_100_pct(self):
        rows = [_row(symbol="AAPL", market_value=1000.0)]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "AAPL")
        self.assertAlmostEqual(result[0]["weight_pct"], 100.0)
        self.assertAlmostEqual(result[0]["market_value"], 1000.0)

    def test_two_positions_weights_sum_to_100(self):
        rows = [
            _row(symbol="AAPL", market_value=600.0),
            _row(symbol="GOOG", market_value=400.0),
        ]
        result = compute_positions_summary(rows, total_mv=1000.0)
        total_weight = sum(p["weight_pct"] for p in result)
        self.assertAlmostEqual(total_weight, 100.0)

    def test_sorted_by_market_value_descending(self):
        rows = [
            _row(symbol="SMALL", market_value=100.0),
            _row(symbol="LARGE", market_value=900.0),
        ]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertEqual(result[0]["symbol"], "LARGE")
        self.assertEqual(result[1]["symbol"], "SMALL")

    def test_same_symbol_different_accounts_merged(self):
        """Two rows for AAPL from different accounts should merge into one entry."""
        rows = [
            _row(symbol="AAPL", market_value=500.0, account_id="ACCT1"),
            _row(symbol="aapl", market_value=300.0, account_id="ACCT2"),  # lowercase
        ]
        result = compute_positions_summary(rows, total_mv=800.0)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["market_value"], 800.0)
        self.assertEqual(result[0]["account_count"], 2)

    def test_symbol_uppercased_for_grouping(self):
        """Lowercase and mixed-case symbols are normalised before grouping."""
        rows = [
            _row(symbol="vfv.to", market_value=400.0),
            _row(symbol="VFV.TO", market_value=600.0),
        ]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "VFV.TO")


class TestComputePositionsSummaryStableKey(unittest.TestCase):

    def test_no_symbol_uses_name_prefix_key(self):
        """Row with security_name but no symbol gets NAME: prefix — not a ticker slot."""
        rows = [_row(security_name="Apple Inc", market_value=1000.0)]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertEqual(len(result), 1)
        # display_symbol should be the real security_name (no NAME: prefix visible)
        self.assertEqual(result[0]["symbol"], "Apple Inc")
        # security_name is preserved from the row
        self.assertEqual(result[0]["security_name"], "Apple Inc")

    def test_no_symbol_no_name_gets_unique_unknown_key(self):
        """Two rows with neither symbol nor name do not merge into one."""
        rows = [
            _row(symbol=None, security_name=None, market_value=500.0),
            _row(symbol=None, security_name=None, market_value=300.0),
        ]
        result = compute_positions_summary(rows, total_mv=800.0)
        self.assertEqual(len(result), 2, "Unidentifiable rows must NOT be merged")

    def test_name_prefix_does_not_collide_with_ticker(self):
        """
        A security named "CASH" should not merge with a ticker symbol "CASH".
        The NAME: prefix key ensures they remain separate entries.
        """
        rows = [
            _row(symbol="CASH",  market_value=500.0),  # actual ticker
            _row(symbol=None, security_name="Cash", market_value=200.0),  # no ticker
        ]
        result = compute_positions_summary(rows, total_mv=700.0)
        self.assertEqual(len(result), 2, "Ticker 'CASH' and NAME:'CASH' must stay separate")

    def test_unknown_rows_display_as_unknown_string(self):
        rows = [_row(symbol=None, security_name=None, market_value=100.0)]
        result = compute_positions_summary(rows, total_mv=100.0)
        self.assertEqual(result[0]["symbol"], "UNKNOWN")


class TestComputePositionsSummaryRegisteredSplit(unittest.TestCase):

    def test_registered_account_type_goes_to_registered_value(self):
        rows = [_row(symbol="AAPL", market_value=1000.0, account_type="TFSA")]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertAlmostEqual(result[0]["registered_value"], 1000.0)
        self.assertAlmostEqual(result[0]["non_registered_value"], 0.0)

    def test_non_registered_account_type_goes_to_non_registered_value(self):
        rows = [_row(symbol="AAPL", market_value=1000.0, account_type="CASH")]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertAlmostEqual(result[0]["registered_value"], 0.0)
        self.assertAlmostEqual(result[0]["non_registered_value"], 1000.0)

    def test_split_across_registered_and_non_registered(self):
        """Same symbol held in both RRSP (registered) and margin (non-registered)."""
        rows = [
            _row(symbol="AAPL", market_value=700.0, account_type="RRSP"),
            _row(symbol="AAPL", market_value=300.0, account_type="MARGIN"),
        ]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["registered_value"], 700.0)
        self.assertAlmostEqual(result[0]["non_registered_value"], 300.0)

    def test_rrsp_is_registered(self):
        rows = [_row(symbol="X", market_value=500.0, account_type="RRSP")]
        result = compute_positions_summary(rows, total_mv=500.0)
        self.assertAlmostEqual(result[0]["registered_value"], 500.0)

    def test_fhsa_is_registered(self):
        rows = [_row(symbol="X", market_value=500.0, account_type="FHSA")]
        result = compute_positions_summary(rows, total_mv=500.0)
        self.assertAlmostEqual(result[0]["registered_value"], 500.0)

    def test_none_account_type_goes_to_non_registered(self):
        """Rows with no account_type at all are treated as non-registered."""
        rows = [_row(symbol="AAPL", market_value=1000.0, account_type=None)]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertAlmostEqual(result[0]["non_registered_value"], 1000.0)


class TestComputePositionsSummaryAccountCount(unittest.TestCase):

    def test_account_count_single_account(self):
        rows = [_row(symbol="AAPL", market_value=1000.0, account_id="ACC1")]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertEqual(result[0]["account_count"], 1)

    def test_account_count_two_distinct_account_ids(self):
        rows = [
            _row(symbol="AAPL", market_value=500.0, account_id="TFSA001"),
            _row(symbol="AAPL", market_value=500.0, account_id="RRSP002"),
        ]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertEqual(result[0]["account_count"], 2)

    def test_account_count_same_account_id_counted_once(self):
        rows = [
            _row(symbol="AAPL", market_value=500.0, account_id="ACC1"),
            _row(symbol="AAPL", market_value=300.0, account_id="ACC1"),
        ]
        result = compute_positions_summary(rows, total_mv=800.0)
        self.assertEqual(result[0]["account_count"], 1)

    def test_account_count_composite_fallback_used_when_no_account_id(self):
        """Without an account_id, type@institution@currency is the fallback key."""
        rows = [
            _row(symbol="AAPL", market_value=500.0,
                 account_type="TFSA", institution="TD", currency="CAD"),
            _row(symbol="AAPL", market_value=300.0,
                 account_type="RRSP", institution="TD", currency="CAD"),
        ]
        result = compute_positions_summary(rows, total_mv=800.0)
        self.assertEqual(result[0]["account_count"], 2)

    def test_account_count_composite_same_composite_counted_once(self):
        rows = [
            _row(symbol="AAPL", market_value=500.0,
                 account_type="TFSA", institution="TD", currency="CAD"),
            _row(symbol="AAPL", market_value=300.0,
                 account_type="TFSA", institution="TD", currency="CAD"),
        ]
        result = compute_positions_summary(rows, total_mv=800.0)
        self.assertEqual(result[0]["account_count"], 1)


class TestComputePositionsSummaryDescriptiveFields(unittest.TestCase):

    def test_sector_defaults_to_unknown(self):
        rows = [_row(symbol="AAPL", market_value=1000.0, sector=None)]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertEqual(result[0]["sector"], "unknown")

    def test_asset_class_defaults_to_unknown(self):
        rows = [_row(symbol="AAPL", market_value=1000.0, asset_class=None)]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertEqual(result[0]["asset_class"], "unknown")

    def test_first_non_none_sector_wins(self):
        """Rows are processed in order; first non-None sector is kept."""
        rows = [
            _row(symbol="AAPL", market_value=400.0, sector=None),
            _row(symbol="AAPL", market_value=400.0, sector="Technology"),
            _row(symbol="AAPL", market_value=200.0, sector="Other"),
        ]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertEqual(result[0]["sector"], "Technology")

    def test_security_name_carried_through(self):
        rows = [_row(symbol="AAPL", security_name="Apple Inc", market_value=1000.0)]
        result = compute_positions_summary(rows, total_mv=1000.0)
        self.assertEqual(result[0]["security_name"], "Apple Inc")


class TestComputePositionsSummaryOutputShape(unittest.TestCase):

    def test_all_required_keys_present(self):
        rows = [_row(symbol="AAPL", market_value=1000.0)]
        result = compute_positions_summary(rows, total_mv=1000.0)
        required_keys = {
            "symbol", "security_name", "sector", "asset_class",
            "market_value", "weight_pct", "registered_value",
            "non_registered_value", "account_count",
        }
        self.assertEqual(set(result[0].keys()), required_keys)

    def test_no_row_level_fields_in_output(self):
        """
        GOVERNANCE: internal accumulation keys (_display_symbol, _account_keys, etc.)
        must not leak into the output dicts.
        """
        rows = [_row(symbol="AAPL", market_value=1000.0)]
        result = compute_positions_summary(rows, total_mv=1000.0)
        for key in result[0]:
            self.assertFalse(
                key.startswith("_"),
                f"Private accumulator key leaked into output: {key!r}",
            )


if __name__ == "__main__":
    unittest.main()
