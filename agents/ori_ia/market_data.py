"""
agents/ori_ia/market_data.py
─────────────────────────────
Live market price and dividend data fetching for ORI Personal.

GOVERNANCE
----------
- This module makes NETWORK CALLS to Yahoo Finance via yfinance.
- It must only be called from an explicitly gated action (portfolio_prices_v0).
- It must never be called automatically or on import.
- Results are returned as aggregates — quantity is passed in so annual income
  can be computed here, but raw position details are not stored.

Symbol resolution
-----------------
Priority order:
  1. refs/symbols.yaml yahoo_symbol field (explicit override)
       - null  → skip this symbol (no market data — structured notes, money market)
       - str   → use as-is (US, OTC, TSX-V, unit trusts)
  2. Default → append ".TO"  (standard TSX equities and ETFs)

Returns
-------
dict keyed by the ORIGINAL broker symbol (uppercase), each value:
    {
        yahoo_symbol:        str | None,
        price:               float | None,
        currency:            str,          e.g. "CAD" or "USD"
        dividend_rate:       float | None, annual $ per share (in local currency)
        dividend_yield_pct:  float | None, e.g. 4.5  (percent, not decimal)
        annual_income:       float | None, quantity * dividend_rate
        stale:               bool,         True if we fell back to last_price
        stale_reason:        str | None,
        last_price:          float | None, last known price from portfolio CSV
    }
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Symbol resolution
# ---------------------------------------------------------------------------

def resolve_yahoo_symbol(broker_symbol: str, ref_entry: dict | None) -> str | None:
    """
    Resolve a broker symbol to its Yahoo Finance equivalent.

    Returns None if the symbol has no market data (yahoo_symbol: null in refs).
    """
    if ref_entry is not None and "yahoo_symbol" in ref_entry:
        # Explicit override — could be a string or null
        override = ref_entry["yahoo_symbol"]
        if override is None:
            return None          # no market data for this symbol
        return str(override)

    # Default: TSX — append .TO
    return broker_symbol + ".TO"


# ---------------------------------------------------------------------------
# Single ticker fetch
# ---------------------------------------------------------------------------

def _fetch_one(
    broker_symbol: str,
    yahoo_symbol: str,
    quantity: float,
    last_price: float | None,
) -> dict:
    """
    Fetch price and dividend data for one symbol from Yahoo Finance.

    Falls back to last_price on any error.
    """
    result: dict[str, Any] = {
        "yahoo_symbol":       yahoo_symbol,
        "price":              None,
        "currency":           "CAD",
        "dividend_rate":      None,
        "dividend_yield_pct": None,
        "annual_income":      None,
        "stale":              False,
        "stale_reason":       None,
        "last_price":         last_price,
    }

    try:
        import yfinance as yf  # lazy import — network dep, not available in tests
    except ImportError:
        result["stale"] = True
        result["stale_reason"] = "yfinance not installed (pip install yfinance)"
        result["price"] = last_price
        return result

    try:
        ticker = yf.Ticker(yahoo_symbol)
        info = ticker.info

        # Price — try multiple fields yfinance may use
        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("navPrice")
        )
        if price is None:
            raise ValueError(f"No price returned for {yahoo_symbol!r}")

        result["price"]    = float(price)
        result["currency"] = info.get("currency", "CAD")

        # Dividend data
        div_rate = info.get("dividendRate") or 0.0
        div_yield = info.get("dividendYield") or 0.0   # decimal, e.g. 0.045
        result["dividend_rate"]      = float(div_rate)
        result["dividend_yield_pct"] = round(float(div_yield) * 100, 4)

        if div_rate and quantity:
            result["annual_income"] = round(float(div_rate) * float(quantity), 2)

    except Exception as exc:
        logger.warning("market_data: failed to fetch %s (%s): %s", broker_symbol, yahoo_symbol, exc)
        result["stale"]        = True
        result["stale_reason"] = str(exc)
        result["price"]        = last_price

    return result


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def fetch_prices(
    positions: list[dict],
    symbol_refs: dict[str, dict],
) -> dict[str, dict]:
    """
    Fetch current prices and dividend data for a list of portfolio positions.

    Parameters
    ----------
    positions : list[dict]
        Each entry must have: symbol (str), quantity (float), market_value (float).
        market_value / quantity is used as last_known_price fallback.
    symbol_refs : dict[str, dict]
        Parsed from refs/symbols.yaml — keyed by uppercase symbol.
        Used to resolve Yahoo Finance symbols.

    Returns
    -------
    dict[str, dict]
        Keyed by original broker symbol (uppercase).
        See module docstring for per-symbol field definitions.

    Notes
    -----
    - Symbols with yahoo_symbol: null are returned with stale=True and
      price=last_price immediately (no network call attempted).
    - Each ticker fetch is independent; one failure does not block others.
    """
    results: dict[str, dict] = {}

    for pos in positions:
        symbol   = str(pos.get("symbol", "")).upper()
        quantity = float(pos.get("quantity") or 0)
        mv       = float(pos.get("market_value") or 0)

        # Derive last known per-share price from market_value / quantity
        last_price: float | None = None
        if quantity and mv:
            last_price = round(mv / quantity, 4)

        ref_entry = symbol_refs.get(symbol)
        yahoo_sym = resolve_yahoo_symbol(symbol, ref_entry)

        if yahoo_sym is None:
            # No market data for this symbol (structured note, money market, etc.)
            results[symbol] = {
                "yahoo_symbol":       None,
                "price":              last_price,
                "currency":           "CAD",
                "dividend_rate":      None,
                "dividend_yield_pct": None,
                "annual_income":      None,
                "stale":              True,
                "stale_reason":       "No market data — see yahoo_symbol: null in refs/symbols.yaml",
                "last_price":         last_price,
            }
            continue

        results[symbol] = _fetch_one(symbol, yahoo_sym, quantity, last_price)

    return results


# ---------------------------------------------------------------------------
# Portfolio-level income summary
# ---------------------------------------------------------------------------

def compute_income_summary(price_data: dict[str, dict]) -> dict:
    """
    Compute portfolio-level dividend income totals from fetch_prices output.

    Only CAD-denominated positions are included in the CAD total.
    USD positions are reported separately.

    Returns
    -------
    dict:
        total_annual_income_cad:  float | None
        total_annual_income_usd:  float | None
        income_positions_cad:     int   (positions with CAD dividend data)
        income_positions_usd:     int   (positions with USD dividend data)
        positions_without_data:   int   (stale or no dividend info)
    """
    cad_income = 0.0
    usd_income = 0.0
    cad_count  = 0
    usd_count  = 0
    no_data    = 0

    for sym, data in price_data.items():
        income   = data.get("annual_income")
        currency = data.get("currency", "CAD")

        if income is None or income == 0.0:
            no_data += 1
            continue

        if currency == "USD":
            usd_income += income
            usd_count  += 1
        else:
            cad_income += income
            cad_count  += 1

    return {
        "total_annual_income_cad":  round(cad_income, 2) if cad_count  else None,
        "total_annual_income_usd":  round(usd_income, 2) if usd_count  else None,
        "income_positions_cad":     cad_count,
        "income_positions_usd":     usd_count,
        "positions_without_data":   no_data,
    }
