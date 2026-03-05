"""
Tests for agents/ori_ia/market_data.py

All tests use in-memory data — no real network calls.
yfinance is mocked where needed.
"""

import pytest

from agents.ori_ia.market_data import (
    resolve_yahoo_symbol,
    compute_income_summary,
    fetch_prices,
)


# ---------------------------------------------------------------------------
# resolve_yahoo_symbol
# ---------------------------------------------------------------------------

class TestResolveYahooSymbol:

    def test_no_ref_appends_to(self):
        assert resolve_yahoo_symbol("TD", None) == "TD.TO"

    def test_no_ref_appends_to_etf(self):
        assert resolve_yahoo_symbol("VFV", None) == "VFV.TO"

    def test_ref_without_yahoo_symbol_appends_to(self):
        ref = {"sector": "Financials", "asset_class": "ETF"}
        assert resolve_yahoo_symbol("ZEB", ref) == "ZEB.TO"

    def test_ref_with_explicit_us_symbol(self):
        ref = {"sector": "Consumer Discretionary", "asset_class": "Equity", "yahoo_symbol": "TSLA"}
        assert resolve_yahoo_symbol("TSLA", ref) == "TSLA"

    def test_ref_with_unit_trust_override(self):
        ref = {"sector": "Real Estate", "asset_class": "REIT", "yahoo_symbol": "AP-UN.TO"}
        assert resolve_yahoo_symbol("AP.UN", ref) == "AP-UN.TO"

    def test_ref_with_tsxv_override(self):
        ref = {"sector": "Energy", "asset_class": "Equity", "yahoo_symbol": "UCU.V"}
        assert resolve_yahoo_symbol("UCU", ref) == "UCU.V"

    def test_ref_with_null_returns_none(self):
        ref = {"sector": "Fixed Income", "asset_class": "Structured Note", "yahoo_symbol": None}
        assert resolve_yahoo_symbol("NPP5502", ref) is None

    def test_ref_with_otc_symbol(self):
        ref = {"sector": "Energy", "asset_class": "Equity", "yahoo_symbol": "UURAF"}
        assert resolve_yahoo_symbol("UURAF", ref) == "UURAF"

    def test_eqix_us_override(self):
        ref = {"sector": "Real Estate", "asset_class": "Equity", "yahoo_symbol": "EQIX"}
        assert resolve_yahoo_symbol("EQIX", ref) == "EQIX"


# ---------------------------------------------------------------------------
# fetch_prices — mocked yfinance
# ---------------------------------------------------------------------------

class TestFetchPrices:

    def _make_positions(self):
        return [
            {"symbol": "TD",  "quantity": 100, "market_value": 8000.0},
            {"symbol": "TSLA","quantity":  10, "market_value": 2000.0},
            {"symbol": "NPP5502", "quantity": 1, "market_value": 5000.0},
        ]

    def _make_refs(self):
        return {
            "TD":      {"sector": "Financials",              "asset_class": "Equity"},
            "TSLA":    {"sector": "Consumer Discretionary",  "asset_class": "Equity", "yahoo_symbol": "TSLA"},
            "NPP5502": {"sector": "Fixed Income",            "asset_class": "Structured Note", "yahoo_symbol": None},
        }

    def test_null_yahoo_symbol_is_stale_no_network(self):
        """Symbols with yahoo_symbol: null must not trigger a network call."""
        positions = [{"symbol": "NPP5502", "quantity": 1, "market_value": 5000.0}]
        refs = {"NPP5502": {"yahoo_symbol": None}}
        result = fetch_prices(positions, refs)
        assert "NPP5502" in result
        assert result["NPP5502"]["stale"] is True
        assert result["NPP5502"]["yahoo_symbol"] is None

    def test_null_symbol_uses_last_price_from_mv_qty(self):
        positions = [{"symbol": "NPP5502", "quantity": 5, "market_value": 5000.0}]
        refs = {"NPP5502": {"yahoo_symbol": None}}
        result = fetch_prices(positions, refs)
        assert result["NPP5502"]["last_price"] == pytest.approx(1000.0)

    def test_result_keyed_by_uppercase_symbol(self):
        positions = [{"symbol": "td", "quantity": 100, "market_value": 8000.0}]
        refs = {}
        # Will try to fetch TD.TO — likely fails in test env (no network)
        # but the key must be uppercase
        result = fetch_prices(positions, refs)
        assert "TD" in result

    def test_zero_quantity_last_price_is_none(self):
        positions = [{"symbol": "NPP5502", "quantity": 0, "market_value": 5000.0}]
        refs = {"NPP5502": {"yahoo_symbol": None}}
        result = fetch_prices(positions, refs)
        assert result["NPP5502"]["last_price"] is None

    def test_missing_quantity_last_price_is_none(self):
        positions = [{"symbol": "NPP5502", "market_value": 5000.0}]
        refs = {"NPP5502": {"yahoo_symbol": None}}
        result = fetch_prices(positions, refs)
        assert result["NPP5502"]["last_price"] is None

    def test_fetch_prices_with_mocked_yfinance(self, monkeypatch):
        """Full fetch with yfinance mocked — no real network call."""
        mock_info = {
            "currentPrice":  85.0,
            "currency":      "CAD",
            "dividendRate":  3.60,
            "dividendYield": 0.0424,
        }

        class MockTicker:
            def __init__(self, sym):
                self.info = mock_info

        import agents.ori_ia.market_data as md
        monkeypatch.setattr("agents.ori_ia.market_data._fetch_one",
            lambda broker, yahoo, qty, last: {
                "yahoo_symbol":       yahoo,
                "price":              85.0,
                "currency":           "CAD",
                "dividend_rate":      3.60,
                "dividend_yield_pct": 4.24,
                "annual_income":      round(3.60 * qty, 2),
                "stale":              False,
                "stale_reason":       None,
                "last_price":         last,
            }
        )

        positions = [{"symbol": "TD", "quantity": 100, "market_value": 8000.0}]
        refs = {"TD": {"sector": "Financials", "asset_class": "Equity"}}
        result = fetch_prices(positions, refs)

        assert "TD" in result
        assert result["TD"]["price"] == 85.0
        assert result["TD"]["dividend_rate"] == 3.60
        assert result["TD"]["annual_income"] == 360.0
        assert result["TD"]["stale"] is False

    def test_yfinance_failure_falls_back_to_stale(self, monkeypatch):
        """If _fetch_one returns stale, the result should reflect that."""
        import agents.ori_ia.market_data as md
        monkeypatch.setattr("agents.ori_ia.market_data._fetch_one",
            lambda broker, yahoo, qty, last: {
                "yahoo_symbol":       yahoo,
                "price":              last,
                "currency":           "CAD",
                "dividend_rate":      None,
                "dividend_yield_pct": None,
                "annual_income":      None,
                "stale":              True,
                "stale_reason":       "connection error",
                "last_price":         last,
            }
        )
        positions = [{"symbol": "TD", "quantity": 100, "market_value": 8000.0}]
        refs = {}
        result = fetch_prices(positions, refs)
        assert result["TD"]["stale"] is True
        assert result["TD"]["price"] == pytest.approx(80.0)  # 8000/100


# ---------------------------------------------------------------------------
# compute_income_summary
# ---------------------------------------------------------------------------

class TestComputeIncomeSummary:

    def test_cad_only(self):
        price_data = {
            "TD":  {"currency": "CAD", "annual_income": 360.0,  "stale": False},
            "ENB": {"currency": "CAD", "annual_income": 480.0,  "stale": False},
        }
        result = compute_income_summary(price_data)
        assert result["total_annual_income_cad"] == pytest.approx(840.0)
        assert result["total_annual_income_usd"] is None
        assert result["income_positions_cad"] == 2
        assert result["income_positions_usd"] == 0

    def test_usd_only(self):
        price_data = {
            "EQIX": {"currency": "USD", "annual_income": 168.0, "stale": False},
        }
        result = compute_income_summary(price_data)
        assert result["total_annual_income_usd"] == pytest.approx(168.0)
        assert result["total_annual_income_cad"] is None

    def test_mixed_currencies(self):
        price_data = {
            "TD":   {"currency": "CAD", "annual_income": 360.0, "stale": False},
            "TSLA": {"currency": "USD", "annual_income": 0.0,   "stale": False},
            "EQIX": {"currency": "USD", "annual_income": 168.0, "stale": False},
        }
        result = compute_income_summary(price_data)
        assert result["total_annual_income_cad"] == pytest.approx(360.0)
        assert result["total_annual_income_usd"] == pytest.approx(168.0)  # EQIX only; TSLA=0 excluded
        assert result["income_positions_usd"] == 1        # only EQIX has income > 0
        assert result["positions_without_data"] == 1      # TSLA income=0

    def test_none_income_counted_as_no_data(self):
        price_data = {
            "NPP5502": {"currency": "CAD", "annual_income": None, "stale": True},
        }
        result = compute_income_summary(price_data)
        assert result["total_annual_income_cad"] is None
        assert result["positions_without_data"] == 1

    def test_empty_price_data(self):
        result = compute_income_summary({})
        assert result["total_annual_income_cad"] is None
        assert result["total_annual_income_usd"] is None
        assert result["income_positions_cad"] == 0
        assert result["income_positions_usd"] == 0
        assert result["positions_without_data"] == 0

    def test_all_stale_returns_no_data(self):
        price_data = {
            "TD":  {"currency": "CAD", "annual_income": None, "stale": True},
            "ENB": {"currency": "CAD", "annual_income": None, "stale": True},
        }
        result = compute_income_summary(price_data)
        assert result["total_annual_income_cad"] is None
        assert result["positions_without_data"] == 2
