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

from agents.ori_ia.schema import NON_REGISTERED_ACCOUNT_TYPES, REGISTERED_ACCOUNT_TYPES

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


def compute_positions_summary(
    rows: list[dict],
    total_mv: float,
) -> list[dict]:
    """
    Compute a per-symbol aggregate breakdown of the portfolio.

    GOVERNANCE: Aggregates only — no row-level holdings data is returned.
    Each entry collapses all rows that share the same ticker across every
    loaded account into a single summary record.

    Grouping key design (prevents spurious merges of unrelated holdings):
      - Ticker present    → symbol.strip().upper()          e.g. "AAPL"
      - Ticker absent     → "NAME:<security_name.upper()>"  avoids collision
                            with real tickers
      - Neither available → "UNKNOWN:<row_index>"           unique per row,
                            prevents unrelated no-ID positions from pooling

    Account-count key priority (identifies distinct accounts stably):
      1. account_id  — explicit account number from CSV or manifest injection
      2. f"{account_type}@{institution}@{currency}" — composite fallback
         (manifest 'label' is not injected into canonical rows, so it is
         not available here; account_id is the correct unique handle)

    Args:
        rows:     Normalized rows (canonical dicts from normalize_csv /
                  enriched by enrich_rows and manifest injection).
        total_mv: Pre-computed total portfolio market value (from
                  compute_total_market_value).  Must be > 0.

    Returns:
        List of per-symbol dicts sorted by market_value descending.
        Each dict:
            symbol               str    — ticker, security_name, or "UNKNOWN:<n>"
            security_name        str|None
            sector               str    — "unknown" when absent
            asset_class          str    — "unknown" when absent
            market_value         float  — sum across all accounts, rounded 2dp
            weight_pct           float  — market_value / total_mv * 100, 2dp
            registered_value     float  — mv from REGISTERED_ACCOUNT_TYPES rows
            non_registered_value float  — mv from NON_REGISTERED_ACCOUNT_TYPES rows
            unclassified_value   float  — mv from rows with unrecognised account_type;
                                          absorbs any floating-point reconciliation delta
            account_count        int    — distinct accounts holding this symbol
        Returns [] when total_mv is 0.

        Invariant (after reconciliation):
            registered_value + non_registered_value + unclassified_value == market_value
    """
    if total_mv == 0:
        logger.warning("total_mv is 0 — cannot compute positions summary")
        return []

    # accum: grouping_key → running aggregate dict
    accum: dict[str, dict] = {}

    for row_index, r in enumerate(rows):
        # ── Stable grouping key ─────────────────────────────────────────────
        raw_symbol = r.get("symbol")
        raw_name   = r.get("security_name")

        if raw_symbol and raw_symbol.strip():
            key            = raw_symbol.strip().upper()
            display_symbol = raw_symbol.strip().upper()
        elif raw_name and raw_name.strip():
            # Prefix prevents "APPLE INC" from ever colliding with a ticker
            # whose uppercased value happens to match the security name.
            key            = f"NAME:{raw_name.strip().upper()}"
            display_symbol = raw_name.strip()
        else:
            # Row has no usable identifier — give it a unique slot so it is
            # never merged with any other unidentifiable row.
            key            = f"UNKNOWN:{row_index}"
            display_symbol = "UNKNOWN"

        mv = r.get("market_value") or 0.0

        if key not in accum:
            accum[key] = {
                "_display_symbol":    display_symbol,
                "_security_name":     raw_name,
                "_sector":            None,
                "_asset_class":       None,
                "market_value":       0.0,
                "registered_value":   0.0,
                "non_registered_value": 0.0,
                "unclassified_value": 0.0,
                "_account_keys":      set(),
            }

        entry = accum[key]
        entry["market_value"] += mv

        # First non-None descriptive value encountered wins for each field.
        if entry["_security_name"] is None and raw_name:
            entry["_security_name"] = raw_name
        if entry["_sector"] is None and r.get("sector"):
            entry["_sector"] = r.get("sector")
        if entry["_asset_class"] is None and r.get("asset_class"):
            entry["_asset_class"] = r.get("asset_class")

        # ── Three-bucket classification ─────────────────────────────────────
        # registered        → REGISTERED_ACCOUNT_TYPES (schema.py)
        # non_registered    → NON_REGISTERED_ACCOUNT_TYPES (schema.py)
        # unclassified      → anything else, including empty/None account_type
        #
        # "unclassified" is intentionally distinct from "non_registered" so
        # that data-quality gaps (unknown account types) are visible rather
        # than silently absorbed into a known bucket.
        raw_type = (r.get("account_type") or "").strip().upper()
        if raw_type in REGISTERED_ACCOUNT_TYPES:
            entry["registered_value"] += mv
        elif raw_type in NON_REGISTERED_ACCOUNT_TYPES:
            entry["non_registered_value"] += mv
        else:
            entry["unclassified_value"] += mv

        # ── Account-count key ───────────────────────────────────────────────
        # Note: manifest 'label' is not injected into canonical rows
        # (only account_id / account_type / institution / currency are injected),
        # so the priority here is: account_id → composite fallback.
        acct_id   = r.get("account_id")
        acct_type = r.get("account_type") or ""
        acct_inst = r.get("institution") or ""
        acct_ccy  = r.get("currency") or ""

        if acct_id and str(acct_id).strip():
            acct_key = str(acct_id).strip()
        else:
            acct_key = f"{acct_type}@{acct_inst}@{acct_ccy}"

        entry["_account_keys"].add(acct_key)

    # ── Build output list ───────────────────────────────────────────────────
    result = []
    for entry in accum.values():
        mv   = round(entry["market_value"], 2)
        reg  = round(entry["registered_value"], 2)
        nreg = round(entry["non_registered_value"], 2)
        uncl = round(entry["unclassified_value"], 2)

        # Reconciliation: rounding each sub-total independently can introduce
        # a ±0.01 cent discrepancy.  Fold any delta into unclassified_value so
        # the three buckets always sum exactly to market_value.
        classified_total = round(reg + nreg + uncl, 2)
        delta = round(mv - classified_total, 2)
        if abs(delta) >= 0.01:
            uncl = round(uncl + delta, 2)

        result.append({
            "symbol":               entry["_display_symbol"],
            "security_name":        entry["_security_name"],
            "sector":               entry["_sector"] or "unknown",
            "asset_class":          entry["_asset_class"] or "unknown",
            "market_value":         mv,
            "weight_pct":           round((mv / total_mv) * 100, 2),
            "registered_value":     reg,
            "non_registered_value": nreg,
            "unclassified_value":   uncl,
            "account_count":        len(entry["_account_keys"]),
        })

    return sorted(result, key=lambda p: p["market_value"], reverse=True)


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
        # GOVERNANCE: aggregates only — no row-level data.
        # compute_positions_summary produces one entry per unique symbol;
        # registered_value, non_registered_value, and unclassified_value are
        # sub-totals that always sum to market_value (reconciliation enforced).
        "positions_summary": compute_positions_summary(rows, total_mv),
    }
