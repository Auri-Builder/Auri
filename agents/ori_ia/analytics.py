"""
ORI_IA Analytics Module
========================
All functions are pure: they accept normalized rows (list of canonical dicts
produced by normalize.py) and return structured dicts.

No file I/O. No network calls. No side effects.

These functions implement ORI_IA Phase 2 — Policy Analysis:
  - Total market value
  - Position weights and top-N ranking
  - Sector exposure
  - Registered vs non-registered split
  - Concentration flags (positions exceeding a configurable threshold)
"""

import logging
from typing import Optional

from agents.ori_ia.schema import REGISTERED_ACCOUNT_TYPES

logger = logging.getLogger(__name__)


def compute_total_market_value(rows: list[dict]) -> float:
    """
    Sum market_value across all normalized rows.

    None values (unmapped or unparseable) are treated as 0 and do not
    raise an error — a missing market_value is simply excluded from the sum.
    """
    return sum(r.get("market_value") or 0.0 for r in rows)


def compute_position_weights(
    rows: list[dict],
    total_mv: float,
) -> dict[str, float]:
    """
    Compute each position's weight as a fraction of total portfolio value.

    Key selection priority: symbol → security_name → "UNKNOWN"
    The same symbol appearing in multiple accounts is accumulated so that
    the weight reflects the total cross-account exposure to that symbol.

    Returns:
        {identifier: weight_as_fraction}  e.g. {"AAPL": 0.12} means 12%.
        Returns {} if total_mv is 0 (prevents division by zero).
    """
    if total_mv == 0:
        logger.warning("total_mv is 0 — cannot compute position weights")
        return {}

    weights: dict[str, float] = {}
    for r in rows:
        # Use the most specific available identifier
        key = (r.get("symbol") or r.get("security_name") or "UNKNOWN").strip()
        mv = r.get("market_value") or 0.0
        weights[key] = weights.get(key, 0.0) + (mv / total_mv)

    return weights


def compute_top_n(
    position_weights: dict[str, float],
    n: int = 5,
) -> list[dict]:
    """
    Return the top N positions by portfolio weight, sorted descending.

    Each entry in the result list:
        {"symbol": str, "weight_pct": float}   (weight_pct is 0–100 scale)
    """
    sorted_items = sorted(position_weights.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"symbol": sym, "weight_pct": round(w * 100, 2)}
        for sym, w in sorted_items[:n]
    ]


def compute_sector_weights(
    rows: list[dict],
    total_mv: float,
) -> dict[str, float]:
    """
    Aggregate market value by sector and express each as a percentage.

    Rows with a None or empty sector field are bucketed under "unknown",
    enabling analysis even when sector data is incomplete.

    Returns:
        {sector_name: weight_pct}   e.g. {"Technology": 28.5, "unknown": 12.0}
        Returns {} if total_mv is 0.
    """
    if total_mv == 0:
        return {}

    sector_totals: dict[str, float] = {}
    for r in rows:
        sector = (r.get("sector") or "").strip() or "unknown"
        mv = r.get("market_value") or 0.0
        sector_totals[sector] = sector_totals.get(sector, 0.0) + mv

    return {
        sector: round((mv / total_mv) * 100, 2)
        for sector, mv in sorted(sector_totals.items(), key=lambda kv: kv[1], reverse=True)
    }


def compute_account_type_split(
    rows: list[dict],
    account_type_override: Optional[str] = None,
) -> dict[str, float]:
    """
    Split total market value into registered, non_registered, and unclassified.

    Classification logic:
      1. Use the row's account_type field if present.
      2. Fall back to account_type_override (job param) if the row has no type.
      3. If neither is available → "unclassified".

    REGISTERED_ACCOUNT_TYPES (schema.py) is the authoritative lookup.
    Comparison is case-insensitive (uppercased before lookup).

    Returns:
        Absolute market values (not fractions) per bucket, rounded to 2dp.
        Zero-value buckets are omitted for cleaner output.
        e.g. {"registered": 85000.00, "non_registered": 42000.00}
    """
    buckets: dict[str, float] = {
        "registered": 0.0,
        "non_registered": 0.0,
        "unclassified": 0.0,
    }

    for r in rows:
        # Row-level type takes priority over the override param
        raw_type = (r.get("account_type") or account_type_override or "").strip()
        upper_type = raw_type.upper()
        mv = r.get("market_value") or 0.0

        if not upper_type:
            bucket = "unclassified"
        elif upper_type in REGISTERED_ACCOUNT_TYPES:
            bucket = "registered"
        else:
            bucket = "non_registered"

        buckets[bucket] += mv

    # Drop zero-value buckets to keep output minimal
    return {k: round(v, 2) for k, v in buckets.items() if v != 0.0}


def compute_concentration_flags(
    position_weights: dict[str, float],
    threshold: float = 0.10,
) -> list[dict]:
    """
    Identify positions whose portfolio weight exceeds the concentration threshold.

    A concentration flag indicates that a single position represents an
    outsized share of the portfolio, which may represent unintended risk.

    Default threshold: 10% (0.10 as a fraction).

    Returns:
        Sorted descending by weight. Each entry:
        {"symbol": str, "weight_pct": float, "flag": "CONCENTRATION_ALERT"}
    """
    flags = [
        {
            "symbol": sym,
            "weight_pct": round(weight * 100, 2),
            "flag": "CONCENTRATION_ALERT",
        }
        for sym, weight in position_weights.items()
        if weight > threshold
    ]
    return sorted(flags, key=lambda f: f["weight_pct"], reverse=True)


def build_summary(
    rows: list[dict],
    concentration_threshold: float = 0.10,
    top_n: int = 5,
    account_type_override: Optional[str] = None,
) -> dict:
    """
    Master analytics function. Composes all analytics functions into a
    single structured summary dict.

    Args:
        rows:                    Normalized rows from normalize_csv()
        concentration_threshold: Fraction above which a position is flagged
                                 (default 0.10 = 10%)
        top_n:                   Number of top positions to include
                                 (default 5)
        account_type_override:   Account type to apply to rows that have no
                                 account_type field (e.g. "RRSP" or "TFSA")

    Returns:
        Aggregates only — no raw row data is included in the output.
        {
            "total_market_value":      float,
            "position_count":          int,
            "unique_symbols":          int,
            "top_positions":           [{symbol, weight_pct}, ...],
            "sector_weights_pct":      {sector: pct, ...},
            "account_type_split":      {bucket: market_value, ...},
            "concentration_flags":     [{symbol, weight_pct, flag}, ...],
            "concentration_threshold_pct": float,
        }
    """
    total_mv = compute_total_market_value(rows)
    position_weights = compute_position_weights(rows, total_mv)

    return {
        "total_market_value": round(total_mv, 2),
        "position_count": len(rows),
        "unique_symbols": len(position_weights),
        "top_positions": compute_top_n(position_weights, top_n),
        "sector_weights_pct": compute_sector_weights(rows, total_mv),
        "account_type_split": compute_account_type_split(rows, account_type_override),
        "concentration_flags": compute_concentration_flags(position_weights, concentration_threshold),
        "concentration_threshold_pct": round(concentration_threshold * 100, 1),
    }
