"""
agents/ori_wb/rebalancer.py
---------------------------
Portfolio drift detection and rebalancing guidance.

Given current holdings (as a list of positions with asset-class tags)
and a target allocation, computes:
  - Current allocation % by bucket (equities / bonds / cash)
  - Drift from target (percentage points)
  - Rebalancing trades: which buckets to trim/add and by how much ($)
  - "Buy-only" mode: grow under-weight buckets without selling (for
    tax-efficiency in non-registered accounts)

Asset class tagging is based on the `asset_class` field in each position.
Recognised tags: equity, bond, gic, cash, reit (treated as equity here).
Unknown tags fall into "other" and are excluded from drift calculation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Mapping from asset_class tags → our three buckets
_BUCKET_MAP = {
    "equity":        "equities",
    "equities":      "equities",
    "stock":         "equities",
    "reit":          "equities",
    "etf":           "equities",   # default; user may override
    "bond":          "bonds",
    "bonds":         "bonds",
    "fixed income":  "bonds",
    "gic":           "bonds",
    "gics":          "bonds",
    "preferred":     "bonds",
    "cash":          "cash",
    "money market":  "cash",
    "hisa":          "cash",
    "savings":       "cash",
    "t-bill":        "cash",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class HoldingInput:
    symbol:      str
    name:        str
    market_value: float
    asset_class: str    # use tags from _BUCKET_MAP; unknown → "other"


@dataclass
class BucketSummary:
    bucket:       str    # equities / bonds / cash / other
    value:        float
    pct:          float
    target_pct:   float
    drift_pp:     float  # current_pct - target_pct


@dataclass
class TradeGuidance:
    bucket:       str
    action:       str    # "Reduce" or "Increase"
    drift_pp:     float  # how far off target (absolute)
    amount:       float  # $ to shift if doing a full rebalance
    buy_only_amount: float  # $ of new contributions to direct here (buy-only mode)


@dataclass
class RebalanceResult:
    total_value:       float
    buckets:           list[BucketSummary]
    trades:            list[TradeGuidance]   # sorted largest drift first
    needs_rebalance:   bool
    max_drift_pp:      float
    threshold_pp:      float
    # Positions that couldn't be classified
    unclassified:      list[str]


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def analyse_drift(
    holdings:            list[HoldingInput],
    target_equities_pct: float,
    target_bonds_pct:    float,
    target_cash_pct:     float,
    rebalance_threshold: float = 5.0,   # pp
    new_contributions:   float = 0.0,   # optional: annual new money to direct
) -> RebalanceResult:
    """
    Compute current allocation vs target and generate rebalancing guidance.
    """
    # ── Bucket aggregation ────────────────────────────────────────────────
    buckets_val: dict[str, float] = {"equities": 0.0, "bonds": 0.0, "cash": 0.0, "other": 0.0}
    unclassified: list[str] = []

    for h in holdings:
        bucket = _BUCKET_MAP.get(h.asset_class.lower().strip(), "other")
        buckets_val[bucket] += h.market_value
        if bucket == "other" and h.asset_class.lower().strip() not in ("other", ""):
            unclassified.append(f"{h.symbol} ({h.asset_class})")

    total = sum(buckets_val.values())
    if total <= 0:
        return RebalanceResult(
            total_value=0, buckets=[], trades=[], needs_rebalance=False,
            max_drift_pp=0, threshold_pp=rebalance_threshold, unclassified=unclassified,
        )

    # Exclude "other" from pct calc so the three recognised buckets sum to 100%
    recognised = total - buckets_val["other"]
    if recognised <= 0:
        recognised = total

    targets = {"equities": target_equities_pct, "bonds": target_bonds_pct, "cash": target_cash_pct}

    bucket_rows: list[BucketSummary] = []
    for b in ("equities", "bonds", "cash"):
        val    = buckets_val[b]
        pct    = (val / recognised * 100.0) if recognised > 0 else 0.0
        tgt    = targets[b]
        drift  = pct - tgt
        bucket_rows.append(BucketSummary(
            bucket     = b,
            value      = val,
            pct        = pct,
            target_pct = tgt,
            drift_pp   = drift,
        ))

    max_drift = max(abs(r.drift_pp) for r in bucket_rows)

    # ── Trade guidance ────────────────────────────────────────────────────
    trades: list[TradeGuidance] = []
    for row in sorted(bucket_rows, key=lambda r: abs(r.drift_pp), reverse=True):
        if abs(row.drift_pp) < 1.0:
            continue  # ignore tiny drifts
        action = "Reduce" if row.drift_pp > 0 else "Increase"
        amount = abs(row.drift_pp / 100.0) * recognised  # $ to shift

        # Buy-only: direct new contributions to under-weight buckets
        # Proportional to how under-weight each bucket is
        under_weight = max(0.0, -row.drift_pp)
        total_under  = sum(max(0.0, -r.drift_pp) for r in bucket_rows)
        buy_only = (new_contributions * under_weight / total_under) if total_under > 0 else 0.0

        trades.append(TradeGuidance(
            bucket           = row.bucket,
            action           = action,
            drift_pp         = row.drift_pp,
            amount           = round(amount, 0),
            buy_only_amount  = round(buy_only, 0),
        ))

    return RebalanceResult(
        total_value      = total,
        buckets          = bucket_rows,
        trades           = trades,
        needs_rebalance  = max_drift >= rebalance_threshold,
        max_drift_pp     = max_drift,
        threshold_pp     = rebalance_threshold,
        unclassified     = unclassified,
    )
