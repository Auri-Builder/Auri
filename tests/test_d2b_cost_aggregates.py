"""
tests/test_d2b_cost_aggregates.py
===================================
Unit tests for D2b — per-symbol and portfolio-level cost-basis aggregates.

Covers:
  TestPositionsCostBasis        — cost_basis / unrealized_gain / unrealized_gain_pct
                                  in compute_positions_summary
  TestBuildSummaryTotals        — total_cost_basis / total_unrealized_gain /
                                  total_unrealized_gain_pct in build_summary

All tests use synthetic in-memory rows. No CSV files are read.

Run:
    python -m unittest tests.test_d2b_cost_aggregates   (stdlib)
    python -m pytest tests/                             (if pytest available)
"""

import unittest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(
    symbol="AAPL",
    market_value=1000.0,
    cost_basis=None,
    unrealized_gain=None,
    account_type="TFSA",
    account_id=None,
    security_name=None,
    sector=None,
    asset_class=None,
    institution=None,
    currency="CAD",
) -> dict:
    return {
        "symbol": symbol,
        "security_name": security_name,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "unrealized_gain": unrealized_gain,
        "account_type": account_type,
        "account_id": account_id,
        "institution": institution or "TD",
        "currency": currency,
        "sector": sector,
        "asset_class": asset_class,
        "quantity": None,
        "price": None,
        "unrealized_gain_percent": None,
    }


# ---------------------------------------------------------------------------
# Tests: compute_positions_summary — per-symbol cost aggregates
# ---------------------------------------------------------------------------

class TestPositionsCostBasis(unittest.TestCase):
    """Per-symbol cost_basis, unrealized_gain, unrealized_gain_pct in positions_summary."""

    def setUp(self):
        from agents.ori_ia.analytics import compute_positions_summary
        self.fn = compute_positions_summary

    def test_cost_basis_summed_across_accounts(self):
        """cost_basis sums across two accounts holding the same symbol."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=800.0,  account_type="TFSA"),
            _row(symbol="AAPL", market_value=500.0,  cost_basis=400.0,  account_type="RRSP"),
        ]
        result = self.fn(rows, total_mv=1500.0)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["cost_basis"], 1200.0)

    def test_unrealized_gain_summed_across_accounts(self):
        """unrealized_gain sums across accounts (may include negative values)."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=800.0,  unrealized_gain=200.0,  account_type="TFSA"),
            _row(symbol="AAPL", market_value=500.0,  cost_basis=600.0,  unrealized_gain=-100.0, account_type="RRSP"),
        ]
        result = self.fn(rows, total_mv=1500.0)
        self.assertAlmostEqual(result[0]["unrealized_gain"], 100.0)

    def test_unrealized_gain_pct_computed_from_totals(self):
        """unrealized_gain_pct is computed from aggregated totals, not summed per-row %."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=800.0,  unrealized_gain=200.0),
            _row(symbol="AAPL", market_value=500.0,  cost_basis=400.0,  unrealized_gain=100.0),
        ]
        result = self.fn(rows, total_mv=1500.0)
        # total_cost_basis = 1200, total_unrealized = 300 → 300/1200*100 = 25.0
        self.assertAlmostEqual(result[0]["unrealized_gain_pct"], 25.0)

    def test_negative_unrealized_gain_pct(self):
        """Losses produce a negative unrealized_gain_pct."""
        rows = [
            _row(symbol="AAPL", market_value=700.0, cost_basis=1000.0, unrealized_gain=-300.0),
        ]
        result = self.fn(rows, total_mv=700.0)
        self.assertAlmostEqual(result[0]["unrealized_gain_pct"], -30.0)

    def test_cost_basis_none_when_all_rows_omit_it(self):
        """When no row provides cost_basis, the field is None (not 0)."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=None),
        ]
        result = self.fn(rows, total_mv=1000.0)
        self.assertIsNone(result[0]["cost_basis"])

    def test_unrealized_gain_none_when_all_rows_omit_it(self):
        """When no row provides unrealized_gain, the field is None (not 0)."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, unrealized_gain=None),
        ]
        result = self.fn(rows, total_mv=1000.0)
        self.assertIsNone(result[0]["unrealized_gain"])

    def test_unrealized_gain_pct_none_when_cost_basis_none(self):
        """unrealized_gain_pct is None when cost_basis is None (no basis for %)."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=None, unrealized_gain=100.0),
        ]
        result = self.fn(rows, total_mv=1000.0)
        self.assertIsNone(result[0]["cost_basis"])
        self.assertIsNone(result[0]["unrealized_gain_pct"])

    def test_unrealized_gain_pct_none_when_cost_basis_zero(self):
        """unrealized_gain_pct is None when cost_basis sums to 0 (prevents div-by-zero)."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=0.0, unrealized_gain=50.0),
        ]
        result = self.fn(rows, total_mv=1000.0)
        # cost_basis=0.0 with _has_cost_basis=True → pct guard triggers
        self.assertIsNone(result[0]["unrealized_gain_pct"])

    def test_partial_cost_basis_data_sums_available_rows(self):
        """
        When only some rows report cost_basis, the sum covers only those rows
        (the position-level total is the best available estimate).
        """
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=800.0),
            _row(symbol="AAPL", market_value=500.0,  cost_basis=None),  # no data
        ]
        result = self.fn(rows, total_mv=1500.0)
        # Only the first row contributes → partial sum
        self.assertAlmostEqual(result[0]["cost_basis"], 800.0)

    def test_distinct_symbols_get_independent_cost_aggregates(self):
        """Each symbol has its own independent cost_basis total."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=800.0, unrealized_gain=200.0),
            _row(symbol="GOOG", market_value=500.0,  cost_basis=450.0, unrealized_gain=50.0),
        ]
        result = self.fn(rows, total_mv=1500.0)
        by_symbol = {p["symbol"]: p for p in result}

        self.assertAlmostEqual(by_symbol["AAPL"]["cost_basis"], 800.0)
        self.assertAlmostEqual(by_symbol["GOOG"]["cost_basis"], 450.0)
        self.assertAlmostEqual(by_symbol["AAPL"]["unrealized_gain_pct"], 25.0)
        self.assertAlmostEqual(by_symbol["GOOG"]["unrealized_gain_pct"], round(50/450*100, 2))

    def test_cost_basis_rounded_to_2dp(self):
        """cost_basis output is rounded to 2 decimal places."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=333.333),
            _row(symbol="AAPL", market_value=500.0,  cost_basis=333.333),
        ]
        result = self.fn(rows, total_mv=1500.0)
        # 666.666 rounds to 666.67
        self.assertEqual(result[0]["cost_basis"], 666.67)

    def test_all_three_cost_fields_present_in_output(self):
        """All three D2b fields are present in every positions_summary entry."""
        rows = [_row(symbol="AAPL", market_value=1000.0)]
        result = self.fn(rows, total_mv=1000.0)
        for key in ("cost_basis", "unrealized_gain", "unrealized_gain_pct"):
            self.assertIn(key, result[0], f"Missing key: {key}")


# ---------------------------------------------------------------------------
# Tests: build_summary — portfolio-level cost-basis totals
# ---------------------------------------------------------------------------

class TestBuildSummaryTotals(unittest.TestCase):
    """Portfolio-level total_cost_basis / total_unrealized_gain / total_unrealized_gain_pct."""

    def setUp(self):
        from agents.ori_ia.analytics import build_summary
        self.fn = build_summary

    def test_total_cost_basis_sums_all_positions(self):
        """total_cost_basis is the sum of cost_basis across all positions."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=800.0),
            _row(symbol="GOOG", market_value=500.0,  cost_basis=450.0),
        ]
        summary = self.fn(rows)
        self.assertAlmostEqual(summary["total_cost_basis"], 1250.0)

    def test_total_unrealized_gain_sums_all_positions(self):
        """total_unrealized_gain is the sum of unrealized_gain across all positions."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=800.0,  unrealized_gain=200.0),
            _row(symbol="GOOG", market_value=500.0,  cost_basis=600.0,  unrealized_gain=-100.0),
        ]
        summary = self.fn(rows)
        self.assertAlmostEqual(summary["total_unrealized_gain"], 100.0)

    def test_total_unrealized_gain_pct_computed_from_totals(self):
        """total_unrealized_gain_pct = total_unrealized_gain / total_cost_basis * 100."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=800.0,  unrealized_gain=200.0),
            _row(symbol="GOOG", market_value=500.0,  cost_basis=400.0,  unrealized_gain=100.0),
        ]
        summary = self.fn(rows)
        # total_cb = 1200, total_ug = 300 → 25.0%
        self.assertAlmostEqual(summary["total_unrealized_gain_pct"], 25.0)

    def test_total_cost_basis_none_when_no_positions_have_it(self):
        """total_cost_basis is None when no rows report cost_basis."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=None),
        ]
        summary = self.fn(rows)
        self.assertIsNone(summary["total_cost_basis"])

    def test_total_unrealized_gain_pct_none_when_no_cost_basis(self):
        """total_unrealized_gain_pct is None when total_cost_basis is None."""
        rows = [
            _row(symbol="AAPL", market_value=1000.0, cost_basis=None, unrealized_gain=100.0),
        ]
        summary = self.fn(rows)
        self.assertIsNone(summary["total_unrealized_gain_pct"])

    def test_all_three_total_keys_always_present(self):
        """All three portfolio-level cost fields are always in build_summary output."""
        rows = [_row(symbol="AAPL", market_value=1000.0)]
        summary = self.fn(rows)
        for key in ("total_cost_basis", "total_unrealized_gain", "total_unrealized_gain_pct"):
            self.assertIn(key, summary, f"Missing key: {key}")

    def test_portfolio_totals_match_sum_of_per_symbol_totals(self):
        """
        total_cost_basis == sum of per-symbol cost_basis values in positions_summary.
        Verifies that the two layers of aggregation are consistent.
        """
        rows = [
            _row(symbol="AAPL", market_value=2000.0, cost_basis=1600.0, unrealized_gain=400.0),
            _row(symbol="AAPL", market_value=1000.0, cost_basis=900.0,  unrealized_gain=100.0, account_type="RRSP"),
            _row(symbol="MSFT", market_value=3000.0, cost_basis=2500.0, unrealized_gain=500.0),
        ]
        summary = self.fn(rows)
        ps = summary["positions_summary"]
        summed_cb = sum(p["cost_basis"] for p in ps if p["cost_basis"] is not None)
        self.assertAlmostEqual(summary["total_cost_basis"], summed_cb)

    def test_negative_portfolio_gain(self):
        """A portfolio with losses yields a negative total_unrealized_gain and pct."""
        rows = [
            _row(symbol="AAPL", market_value=700.0, cost_basis=1000.0, unrealized_gain=-300.0),
            _row(symbol="GOOG", market_value=800.0, cost_basis=900.0,  unrealized_gain=-100.0),
        ]
        summary = self.fn(rows)
        self.assertLess(summary["total_unrealized_gain"], 0)
        self.assertLess(summary["total_unrealized_gain_pct"], 0)
        # (−300 − 100) / (1000 + 900) * 100 = −400/1900*100 ≈ −21.05
        self.assertAlmostEqual(
            summary["total_unrealized_gain_pct"],
            round(-400 / 1900 * 100, 2),
        )


if __name__ == "__main__":
    unittest.main()
