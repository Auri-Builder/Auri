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


def compute_account_balance_by_type(
    rows: list[dict],
    account_type_override: Optional[str] = None,
) -> dict[str, float]:
    """
    Break down total market value by specific account type string.

    Unlike compute_account_type_split (which collapses to registered/non_registered),
    this preserves the raw account_type values so downstream agents can distinguish
    RRSP from TFSA from CASH etc.

    Returns:
        {account_type_upper: total_market_value} e.g.
        {"RRSP": 120000.00, "TFSA": 45000.00, "CASH": 30000.00}
        Zero-value types omitted.
    """
    result: dict[str, float] = {}
    for r in rows:
        raw_type  = (r.get("account_type") or account_type_override or "UNCLASSIFIED").strip()
        acct_type = raw_type.upper() or "UNCLASSIFIED"
        mv        = float(r.get("market_value") or 0.0)
        result[acct_type] = result.get(acct_type, 0.0) + mv
    return {k: round(v, 2) for k, v in sorted(result.items()) if v > 0}


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
            cost_basis           float|None — sum of canonical cost_basis across all rows;
                                              None when no row provided this field
            unrealized_gain      float|None — sum of canonical unrealized_gain across all rows;
                                              None when no row provided this field
            unrealized_gain_pct  float|None — unrealized_gain / cost_basis * 100;
                                              None when cost_basis is None or 0
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
                "quantity":           0.0,
                "registered_value":   0.0,
                "non_registered_value": 0.0,
                "unclassified_value": 0.0,
                "_account_keys":      set(),
                # cost-basis aggregates — only accumulated when the row supplies data
                "cost_basis":         0.0,
                "_has_cost_basis":    False,
                "unrealized_gain":    0.0,
                "_has_unrealized":    False,
            }

        entry = accum[key]
        entry["market_value"] += mv
        entry["quantity"]     += r.get("quantity") or 0.0

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

        # ── Cost-basis aggregates ────────────────────────────────────────────
        # Accumulate only non-None values so that rows lacking cost_basis
        # (e.g. from brokers that don't export it) are excluded from the sum
        # rather than pulling the total toward zero.
        cb = r.get("cost_basis")
        if cb is not None:
            entry["cost_basis"] += cb
            entry["_has_cost_basis"] = True

        ug = r.get("unrealized_gain")
        if ug is not None:
            entry["unrealized_gain"] += ug
            entry["_has_unrealized"] = True

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
        # a ±0.01 cent discrepancy.  Capture the raw delta before folding so
        # callers can detect and log the event; then fold into unclassified_value
        # so the three buckets always sum exactly to market_value.
        classified_total = round(reg + nreg + uncl, 2)
        reconciliation_delta = round(mv - classified_total, 2)  # 0.00 in normal operation
        if abs(reconciliation_delta) >= 0.01:
            uncl = round(uncl + reconciliation_delta, 2)

        # ── Cost-basis output ────────────────────────────────────────────────
        cost_basis_out = (
            round(entry["cost_basis"], 2) if entry["_has_cost_basis"] else None
        )
        unrealized_gain_out = (
            round(entry["unrealized_gain"], 2) if entry["_has_unrealized"] else None
        )
        # Compute pct from the aggregated totals — NOT by summing per-row %
        # values (that would be wrong because each row's % is relative to its
        # own cost basis, not the symbol total).
        if cost_basis_out and unrealized_gain_out is not None:
            unrealized_gain_pct = round(unrealized_gain_out / cost_basis_out * 100, 2)
        else:
            unrealized_gain_pct = None

        result.append({
            "symbol":               entry["_display_symbol"],
            "security_name":        entry["_security_name"],
            "sector":               entry["_sector"] or "unknown",
            "asset_class":          entry["_asset_class"] or "unknown",
            "market_value":         mv,
            "quantity":             round(entry["quantity"], 4),
            "weight_pct":           round((mv / total_mv) * 100, 2),
            "registered_value":     reg,
            "non_registered_value": nreg,
            "unclassified_value":   uncl,
            # Diagnostic: non-zero only when rounding produced a ≥0.01 delta.
            # Stored pre-fold so observers can see the original discrepancy.
            # Always 0.00 under normal float arithmetic with real market values.
            "reconciliation_delta": reconciliation_delta,
            "account_count":        len(entry["_account_keys"]),
            "cost_basis":           cost_basis_out,
            "unrealized_gain":      unrealized_gain_out,
            "unrealized_gain_pct":  unrealized_gain_pct,
        })

    return sorted(result, key=lambda p: p["market_value"], reverse=True)


def check_policy(summary: dict, constraints: dict) -> list[dict]:
    """
    Check portfolio summary against investor-defined policy constraints.

    Args:
        summary:     Output of build_summary().
        constraints: The 'constraints' block from profile.yaml, e.g.:
                       max_single_position_pct: 20.0
                       max_sector_pct: 40.0
                       excluded_sectors: ["Tobacco"]

    Returns:
        List of policy flag dicts, each:
            {
                "type":      "position" | "sector" | "excluded_sector",
                "name":      str,    # symbol or sector name
                "value_pct": float,  # actual weight
                "limit_pct": float | None,
                "severity":  "breach" | "warning",
                "message":   str,
            }
        Empty list if no constraints are set or no violations found.

    Severity thresholds:
        breach  — value exceeds the limit
        warning — value is within 15% below the limit (>= 85% of limit)
    """
    if not constraints:
        return []

    flags: list[dict] = []
    _WARNING_RATIO = 0.85  # flag as warning when >= 85% of the limit

    max_pos  = constraints.get("max_single_position_pct")
    max_sec  = constraints.get("max_sector_pct")
    excluded = [s.lower() for s in (constraints.get("excluded_sectors") or [])]

    # ── Position concentration ────────────────────────────────────────────
    if max_pos is not None:
        for pos in summary.get("positions_summary", []):
            sym = pos.get("symbol", "?")
            wt  = pos.get("weight_pct", 0.0) or 0.0
            if wt > max_pos:
                flags.append({
                    "type":      "position",
                    "name":      sym,
                    "value_pct": round(wt, 2),
                    "limit_pct": max_pos,
                    "severity":  "breach",
                    "message":   f"{sym} at {wt:.1f}% exceeds max position limit of {max_pos:.0f}%",
                })
            elif wt >= max_pos * _WARNING_RATIO:
                flags.append({
                    "type":      "position",
                    "name":      sym,
                    "value_pct": round(wt, 2),
                    "limit_pct": max_pos,
                    "severity":  "warning",
                    "message":   f"{sym} at {wt:.1f}% is approaching max position limit of {max_pos:.0f}%",
                })

    # ── Sector concentration ──────────────────────────────────────────────
    if max_sec is not None:
        for sector, pct in summary.get("sector_weights_pct", {}).items():
            if pct > max_sec:
                flags.append({
                    "type":      "sector",
                    "name":      sector,
                    "value_pct": round(pct, 2),
                    "limit_pct": max_sec,
                    "severity":  "breach",
                    "message":   f"{sector} at {pct:.1f}% exceeds max sector limit of {max_sec:.0f}%",
                })
            elif pct >= max_sec * _WARNING_RATIO:
                flags.append({
                    "type":      "sector",
                    "name":      sector,
                    "value_pct": round(pct, 2),
                    "limit_pct": max_sec,
                    "severity":  "warning",
                    "message":   f"{sector} at {pct:.1f}% is approaching max sector limit of {max_sec:.0f}%",
                })

    # ── Excluded sectors ──────────────────────────────────────────────────
    if excluded:
        for pos in summary.get("positions_summary", []):
            sym    = pos.get("symbol", "?")
            sector = (pos.get("sector") or "").lower()
            wt     = pos.get("weight_pct", 0.0) or 0.0
            if sector in excluded:
                flags.append({
                    "type":      "excluded_sector",
                    "name":      sym,
                    "value_pct": round(wt, 2),
                    "limit_pct": 0.0,
                    "severity":  "breach",
                    "message":   f"{sym} is in excluded sector '{pos.get('sector')}'",
                })

    # Sort: breaches first, then warnings; within each group by value descending
    flags.sort(key=lambda f: (0 if f["severity"] == "breach" else 1, -f["value_pct"]))
    return flags


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
            "total_market_value":         float,
            "position_count":             int,
            "unique_symbols":             int,
            "top_positions":              [{symbol, weight_pct}, ...],
            "sector_weights_pct":         {sector: pct, ...},
            "account_type_split":         {bucket: market_value, ...},
            "account_balance_by_type":    {account_type: market_value, ...},
            "concentration_flags":        [{symbol, weight_pct, flag}, ...],
            "concentration_threshold_pct": float,
            "total_cost_basis":           float|None,
            "total_unrealized_gain":      float|None,
            "total_unrealized_gain_pct":  float|None,
        }
    """
    total_mv = compute_total_market_value(rows)
    position_weights = compute_position_weights(rows, total_mv)

    # GOVERNANCE: aggregates only — no row-level data.
    # compute_positions_summary produces one entry per unique symbol;
    # registered_value, non_registered_value, and unclassified_value are
    # sub-totals that always sum to market_value (reconciliation enforced).
    positions_summary = compute_positions_summary(rows, total_mv)

    # Portfolio-level cost-basis aggregates — summed across per-symbol totals.
    # Only positions that reported cost_basis / unrealized_gain data contribute.
    _cb_vals = [p["cost_basis"] for p in positions_summary if p.get("cost_basis") is not None]
    _ug_vals = [p["unrealized_gain"] for p in positions_summary if p.get("unrealized_gain") is not None]
    total_cost_basis = round(sum(_cb_vals), 2) if _cb_vals else None
    total_unrealized_gain = round(sum(_ug_vals), 2) if _ug_vals else None
    if total_cost_basis and total_unrealized_gain is not None:
        total_unrealized_gain_pct = round(total_unrealized_gain / total_cost_basis * 100, 2)
    else:
        total_unrealized_gain_pct = None

    return {
        "total_market_value": round(total_mv, 2),
        "position_count": len(rows),
        "unique_symbols": len(position_weights),
        "top_positions": compute_top_n(position_weights, top_n),
        "sector_weights_pct": compute_sector_weights(rows, total_mv),
        "account_type_split": compute_account_type_split(rows, account_type_override),
        "account_balance_by_type": compute_account_balance_by_type(rows, account_type_override),
        "concentration_flags": compute_concentration_flags(position_weights, concentration_threshold),
        "concentration_threshold_pct": round(concentration_threshold * 100, 1),
        "total_cost_basis":          total_cost_basis,
        "total_unrealized_gain":     total_unrealized_gain,
        "total_unrealized_gain_pct": total_unrealized_gain_pct,
        "positions_summary": positions_summary,
        # Count of positions where rounding produced a ≥0.01 cent discrepancy.
        # Should always be 0; non-zero value signals a float arithmetic anomaly
        # worth investigating (e.g. sub-cent input values).
        "positions_with_delta_folded_count": sum(
            1 for p in positions_summary
            if abs(p.get("reconciliation_delta", 0.0)) >= 0.01
        ),
    }


def suggest_target_allocation(risk_score: float) -> dict:
    """
    Map a risk score (0–100) to a suggested sector target allocation for
    a Canadian retail investor.

    Score tiers:
        0–30   Conservative  — heavy fixed income, minimal equity, modest international
        31–50  Moderate      — balanced income/equity, some international diversification
        51–70  Growth        — equity-tilted, international developed + emerging markets
        71–100 Aggressive    — high equity, full global diversification, minimal income

    All templates include international developed and emerging-market exposure
    to reduce the Canadian home-country + US concentration bias.

    Returns:
        {
            "risk_label":    str,        e.g. "Growth"
            "tolerance_pct": float,      suggested rebalancing tolerance band
            "targets":       {sector: pct},  values sum to 100.0
        }
    """
    if risk_score <= 30:
        label        = "Conservative"
        tolerance    = 5.0
        targets = {
            "Equities - Canada":        10.0,
            "Equities - US":             8.0,
            "Equities - International":  7.0,   # developed markets (EAFE)
            "Fixed Income":             50.0,
            "Money Market":             10.0,
            "Real Estate":               5.0,
            "Energy":                    5.0,
            "Financials":                5.0,
        }
    elif risk_score <= 50:
        label        = "Moderate"
        tolerance    = 5.0
        targets = {
            "Equities - Canada":        18.0,
            "Equities - US":            18.0,
            "Equities - International":  9.0,   # developed markets (EAFE)
            "Equities - Emerging":       5.0,   # emerging markets (EM)
            "Fixed Income":             20.0,
            "Money Market":              5.0,
            "Real Estate":               5.0,
            "Energy":                   10.0,
            "Healthcare":               10.0,
        }
    elif risk_score <= 70:
        label        = "Growth"
        tolerance    = 5.0
        targets = {
            "Equities - Canada":        20.0,
            "Equities - US":            22.0,
            "Equities - International": 13.0,   # developed markets (EAFE)
            "Equities - Emerging":       5.0,   # emerging markets (EM)
            "Financials":               10.0,
            "Fixed Income":             10.0,
            "Money Market":              5.0,
            "Real Estate":               5.0,
            "Energy":                    5.0,
            "Healthcare":                5.0,
        }
    else:
        label        = "Aggressive"
        tolerance    = 7.0
        targets = {
            "Equities - Canada":        20.0,
            "Equities - US":            28.0,
            "Equities - International": 15.0,   # developed markets (EAFE)
            "Equities - Emerging":      10.0,   # emerging markets (EM)
            "Financials":                7.0,
            "Fixed Income":              5.0,
            "Real Estate":               5.0,
            "Energy":                    5.0,
            "Healthcare":                5.0,
        }

    # Drop zero-weight sectors to keep the YAML tidy
    targets = {k: v for k, v in targets.items() if v > 0}

    return {
        "risk_label":    label,
        "tolerance_pct": tolerance,
        "targets":       targets,
    }


def compute_allocation_deviation(
    positions_summary: list[dict],
    targets: dict[str, float],
    total_mv: float,
    tolerance_pct: float = 5.0,
) -> dict:
    """
    Compare actual asset-class weights against user-defined target percentages.

    Args:
        positions_summary: Per-symbol list from build_summary() / compute_positions_summary().
        targets:           {asset_class: target_pct, ...}  — values in percent (e.g. 60.0).
        total_mv:          Total portfolio market value in base currency.
        tolerance_pct:     Deviation threshold below which a band is considered "on target".

    Returns:
        {
            "total_market_value": float,
            "target_sum_pct":     float,
            "tolerance_pct":      float,
            "rows": [
                {
                    "asset_class":      str,
                    "actual_pct":       float,
                    "target_pct":       float,
                    "deviation_pct":    float,   # actual - target; negative = underweight
                    "actual_value":     float,
                    "target_value":     float,
                    "rebalance_amount": float,   # positive = buy, negative = sell
                    "status":           "over" | "under" | "on_target",
                },
                ...
            ],
            "untracked": [
                {"asset_class": str, "actual_pct": float, "actual_value": float},
                ...
            ],
        }
    """
    # Aggregate actual market value per sector from positions
    actual_values: dict[str, float] = {}
    for pos in positions_summary:
        ac = pos.get("sector") or "Unknown"
        mv = pos.get("market_value") or 0.0
        actual_values[ac] = actual_values.get(ac, 0.0) + mv

    # Actual % per sector (safe against zero total_mv)
    def _pct(v: float) -> float:
        return round(v / total_mv * 100, 2) if total_mv > 0 else 0.0

    target_sum = round(sum(targets.values()), 2)

    rows = []
    for ac, target_pct in sorted(targets.items()):
        actual_val = actual_values.get(ac, 0.0)
        actual_pct = _pct(actual_val)
        deviation  = round(actual_pct - target_pct, 2)
        target_val = round(target_pct / 100 * total_mv, 2)
        rebalance  = round(target_val - actual_val, 2)

        if deviation > tolerance_pct:
            status = "over"
        elif deviation < -tolerance_pct:
            status = "under"
        else:
            status = "on_target"

        rows.append({
            "asset_class":      ac,
            "actual_pct":       actual_pct,
            "target_pct":       target_pct,
            "deviation_pct":    deviation,
            "actual_value":     round(actual_val, 2),
            "target_value":     target_val,
            "rebalance_amount": rebalance,
            "status":           status,
        })

    # Asset classes present in the portfolio but not in targets
    untracked = sorted(
        {ac for ac in actual_values if ac not in targets}
    )
    untracked_rows = [
        {
            "asset_class":  ac,
            "actual_pct":   _pct(actual_values[ac]),
            "actual_value": round(actual_values[ac], 2),
        }
        for ac in untracked
    ]

    return {
        "total_market_value": round(total_mv, 2),
        "target_sum_pct":     target_sum,
        "tolerance_pct":      tolerance_pct,
        "rows":               rows,
        "untracked":          untracked_rows,
    }
