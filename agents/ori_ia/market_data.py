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

def _date_to_epoch(date_str: str) -> int:
    """Convert a YYYY-MM-DD string to a Unix timestamp (UTC midnight)."""
    from datetime import datetime, timezone  # noqa: PLC0415
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


_YF_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_YF_HEADERS   = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _yahoo_chart(symbol: str) -> dict:
    """
    Fetch price and dividend data via Yahoo Finance v8 chart API (no API key required).

    Returns a dict with:
        price       : float | None  — regularMarketPrice from meta
        currency    : str
        div_rate    : float | None  — trailing 12-month dividend per share
        div_yield   : float | None  — trailing yield as a decimal (e.g. 0.045)
    """
    import time
    import requests  # noqa: PLC0415

    # Fetch ~13 months of daily data so we capture a full year of dividends
    now    = int(time.time())
    p1     = now - 395 * 86400  # ~13 months back
    resp   = requests.get(
        _YF_CHART_URL.format(symbol=symbol),
        params={"interval": "1d", "period1": p1, "period2": now, "events": "dividends"},
        headers=_YF_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    result_list = resp.json().get("chart", {}).get("result") or []
    if not result_list:
        return {}

    chart  = result_list[0]
    meta   = chart.get("meta", {})
    price  = meta.get("regularMarketPrice")
    currency = meta.get("currency", "CAD")

    # Trailing 12-month dividend: sum dividend events from last 365 days
    cutoff = now - 365 * 86400
    divs   = chart.get("events", {}).get("dividends", {})
    annual_divs = sum(
        float(v["amount"])
        for v in divs.values()
        if v.get("date", 0) >= cutoff
    )

    div_yield = (annual_divs / float(price)) if (price and annual_divs) else None

    return {
        "price":     float(price) if price else None,
        "currency":  currency,
        "div_rate":  round(annual_divs, 4) if annual_divs else None,
        "div_yield": round(div_yield, 6)   if div_yield  else None,
    }


def _fetch_one(
    broker_symbol: str,
    yahoo_symbol: str,
    quantity: float,
    last_price: float | None,
) -> dict:
    """
    Fetch price and dividend data for one symbol via Yahoo Finance v8 chart API.
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
        quote = _yahoo_chart(yahoo_symbol)

        price = quote.get("price")
        if not price:
            raise ValueError(f"No price returned for {yahoo_symbol!r}")

        result["price"]    = price
        result["currency"] = quote.get("currency", "CAD")

        div_rate  = quote.get("div_rate")
        div_yield = quote.get("div_yield") or 0.0

        result["dividend_rate"]      = div_rate
        result["dividend_yield_pct"] = round(div_yield * 100, 4) if div_yield else 0.0

        if div_rate and quantity:
            result["annual_income"] = round(div_rate * quantity, 2)

    except Exception as exc:
        logger.warning("market_data: failed to fetch %s (%s): %s", broker_symbol, yahoo_symbol, exc)
        result["stale"]        = True
        result["stale_reason"] = str(exc)
        result["price"]        = last_price

    return result


# ---------------------------------------------------------------------------
# Globe and Mail / Barchart fund NAV fetch (Canadian mutual funds)
# ---------------------------------------------------------------------------

_BARCHART_EOD_URL = (
    "https://globeandmail.pl.barchart.com/proxies/timeseries/queryeod.ashx"
)
_BARCHART_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
}


def _fetch_globe(
    broker_symbol: str,
    globe_symbol: str,
    quantity: float,
    last_price: float | None,
    distribution_rate_pct: float | None = None,
) -> dict:
    """
    Fetch latest NAV for a Canadian mutual fund from the Globe and Mail /
    Barchart endpoint.

    Returns the same shape as _fetch_one so callers handle both uniformly.
    Response format: SYMBOL,DATE,OPEN,HIGH,LOW,CLOSE,VOLUME  — NAV = CLOSE.

    distribution_rate_pct: annual distribution as % of NAV (from refs/symbols.yaml).
        If provided, annual_income = nav * rate/100 * quantity.
        This is a NAV-based rate (e.g. 14.0 for Ninepoint Energy Income Fund Series F).
    """
    result: dict = {
        "yahoo_symbol":       None,
        "globe_symbol":       globe_symbol,
        "price":              last_price,
        "currency":           "CAD",
        "dividend_rate":      None,
        "dividend_yield_pct": None,
        "annual_income":      None,
        "stale":              True,
        "stale_reason":       None,
        "last_price":         last_price,
    }

    try:
        import requests  # lazy import — network dep  # noqa: PLC0415
        resp = requests.get(
            _BARCHART_EOD_URL,
            params={
                "symbol":      globe_symbol,
                "data":        "daily",
                "maxrecords":  1,
                "volume":      "total",
                "order":       "asc",
                "dividends":   "false",
                "backadjust":  "false",
            },
            headers=_BARCHART_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        line = resp.text.strip()
        if not line:
            raise ValueError(f"Empty response for {globe_symbol!r}")
        parts = line.split(",")
        if len(parts) < 6:
            raise ValueError(f"Unexpected response format: {line!r}")
        nav = float(parts[5])  # CLOSE = NAV
        result["price"] = nav
        result["stale"] = False
        result["stale_reason"] = None

        # Compute income from NAV-based distribution rate if provided
        if distribution_rate_pct and quantity:
            rate = float(distribution_rate_pct)
            result["dividend_yield_pct"] = rate
            result["annual_income"] = round(nav * rate / 100 * quantity, 2)

    except Exception as exc:
        logger.warning("market_data: Globe fetch failed %s (%s): %s", broker_symbol, globe_symbol, exc)
        result["stale_reason"] = str(exc)

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
            # Check for Globe and Mail / Barchart fund symbol (mutual funds)
            globe_sym = ref_entry.get("globe_symbol") if ref_entry else None
            if globe_sym:
                dist_rate = ref_entry.get("distribution_rate_pct") if ref_entry else None
                results[symbol] = _fetch_globe(symbol, globe_sym, quantity, last_price, distribution_rate_pct=dist_rate)
            else:
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


# ---------------------------------------------------------------------------
# Benchmark comparison
# ---------------------------------------------------------------------------

# Well-known Canadian ETF benchmarks for retail investors.
BENCHMARKS: dict[str, str] = {
    "XIU.TO — iShares S&P/TSX 60 (Canadian Equity)":  "XIU.TO",
    "XBAL.TO — iShares Core Balanced (60/40)":         "XBAL.TO",
    "XGRO.TO — iShares Core Growth (80/20)":           "XGRO.TO",
    "XCNS.TO — iShares Core Conservative (40/60)":     "XCNS.TO",
    "VFV.TO — Vanguard S&P 500 (US Equity in CAD)":    "VFV.TO",
    "XWD.TO — iShares MSCI World (Global Equity)":     "XWD.TO",
    "ZAG.TO — BMO Aggregate Bond (Canadian Bonds)":    "ZAG.TO",
}


def fetch_benchmark_return(
    benchmark_symbol: str,
    from_date: str | None = None,
) -> dict:
    """
    Fetch YTD (or since from_date) total return for a benchmark ETF.

    Parameters
    ----------
    benchmark_symbol : str
        Yahoo Finance symbol, e.g. "XIU.TO".
    from_date : str | None
        YYYY-MM-DD start date.  Defaults to current year Jan 1 (YTD).

    Returns
    -------
    dict:
        {
            "symbol":          str,
            "from_date":       str,   YYYY-MM-DD
            "to_date":         str,   YYYY-MM-DD (today)
            "price_start":     float | None,
            "price_end":       float | None,
            "return_pct":      float | None,   e.g. 8.3 for +8.3%
            "currency":        str,
            "stale":           bool,
            "stale_reason":    str | None,
        }

    *** Makes outbound network calls to Yahoo Finance. ***
    """
    from datetime import date, timedelta  # noqa: PLC0415

    today     = date.today()
    start_dt  = date(today.year, 1, 1) if from_date is None else date.fromisoformat(from_date)
    # Buffer: fetch a few extra days to guarantee we get a data point on or before start
    fetch_from = (start_dt - timedelta(days=5)).isoformat()
    fetch_to   = today.isoformat()

    result: dict = {
        "symbol":       benchmark_symbol,
        "from_date":    start_dt.isoformat(),
        "to_date":      today.isoformat(),
        "price_start":  None,
        "price_end":    None,
        "return_pct":   None,
        "currency":     "CAD",
        "stale":        False,
        "stale_reason": None,
    }

    try:
        import requests  # noqa: PLC0415

        # Yahoo Finance v8 chart API — returns OHLCV history, no API key required
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{benchmark_symbol}",
            params={"interval": "1d", "period1": _date_to_epoch(fetch_from), "period2": _date_to_epoch(fetch_to)},
            headers=_YF_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        chart = resp.json()["chart"]["result"][0]
        closes = chart["indicators"]["adjclose"][0]["adjclose"]
        closes = [c for c in closes if c is not None]

        if len(closes) < 2:
            raise ValueError(f"Insufficient history data for {benchmark_symbol!r}")

        price_start = float(closes[0])
        price_end   = float(closes[-1])
        return_pct  = round((price_end - price_start) / price_start * 100, 2)

        result["price_start"] = round(price_start, 4)
        result["price_end"]   = round(price_end,   4)
        result["return_pct"]  = return_pct
        result["currency"]    = chart["meta"].get("currency", "CAD")

    except Exception as exc:
        logger.warning("market_data: benchmark fetch failed %s: %s", benchmark_symbol, exc)
        result["stale"]        = True
        result["stale_reason"] = str(exc)

    return result
