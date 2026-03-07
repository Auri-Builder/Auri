"""
agents/ori_rp/withdrawal.py
-----------------------------
Tax-optimized withdrawal sequencing for the ORI Retirement Planner.

Three strategies are implemented:

1. SIMPLE (Phase 1 default)
   RRIF/RRSP first → Non-registered → TFSA last.
   Minimizes current-year withdrawals from tax-free accounts but ignores
   bracket optimization.

2. BRACKET_FILL
   Fill the current marginal bracket from RRIF first, then draw non-registered
   (50% capital gains inclusion), then TFSA. Keeps taxable income below the
   next bracket threshold where possible — especially useful in the window
   between retirement and RRIF conversion at 71.

3. RRSP_MELTDOWN
   Accelerate RRSP/RRIF withdrawals in low-income years (before CPP/OAS start,
   or before RRIF conversion forces large minimums). Draw RRIF up to a target
   taxable income ceiling (e.g. top of the 2nd federal bracket), then
   non-registered, then TFSA.

All strategies respect the RRIF mandatory minimum — it is taken first regardless
of strategy and cannot be deferred.

Returns
-------
WithdrawalPlan dataclass:
    from_rrif       : float
    from_non_reg    : float
    from_tfsa       : float
    excess_to_non_reg: float   (RRIF min that exceeded spending need → taxable)
    rrif_min_applied: bool
    strategy_used   : str

These values are consumed by the cashflow projection engine.

Disclaimer: Withdrawal sequencing recommendations are for planning purposes only.
Consult a tax advisor before implementing any withdrawal strategy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from agents.ori_rp.tax import estimate_tax, rrif_minimum_withdrawal

logger = logging.getLogger(__name__)


class WithdrawalStrategy(str, Enum):
    SIMPLE        = "simple"
    BRACKET_FILL  = "bracket_fill"
    RRSP_MELTDOWN = "rrsp_meltdown"


@dataclass
class WithdrawalPlan:
    from_rrif:         float
    from_non_reg:      float
    from_tfsa:         float
    excess_to_non_reg: float   # RRIF min that exceeded spending — lands in non-reg
    rrif_min_applied:  bool    # True when min forced withdrawal beyond spending need
    strategy_used:     str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plan_withdrawal(
    spending_need:       float,
    rrif_balance:        float,
    non_reg_balance:     float,
    tfsa_balance:        float,
    other_taxable_income: float,  # CPP + OAS + pension + part-time (already realized)
    age:                 int,
    province:            str = "ON",
    year:                int = 2026,
    strategy:            WithdrawalStrategy = WithdrawalStrategy.SIMPLE,
    is_rrif:             bool = False,
    meltdown_income_ceiling: float | None = None,
) -> WithdrawalPlan:
    """
    Compute the optimal withdrawal split across RRIF, non-registered, and TFSA
    accounts to fund the given spending need under the chosen strategy.

    Parameters
    ----------
    spending_need          : Total dollars needed from portfolio (after guaranteed income).
    rrif_balance           : Current RRSP/RRIF balance.
    non_reg_balance        : Current non-registered balance.
    tfsa_balance           : Current TFSA balance.
    other_taxable_income   : CPP + OAS + pension + part-time (already included in tax calc).
    age                    : Primary person's age this year.
    province               : Two-letter province code.
    year                   : Tax year for bracket lookup.
    strategy               : WithdrawalStrategy enum.
    is_rrif                : True if RRSP has converted to RRIF (age > 71).
    meltdown_income_ceiling: For RRSP_MELTDOWN — target taxable income ceiling.
                             Defaults to top of 2nd federal bracket (~$114,750 in 2026).
    """
    if strategy == WithdrawalStrategy.BRACKET_FILL:
        return _bracket_fill(
            spending_need, rrif_balance, non_reg_balance, tfsa_balance,
            other_taxable_income, age, province, year, is_rrif,
        )
    elif strategy == WithdrawalStrategy.RRSP_MELTDOWN:
        return _rrsp_meltdown(
            spending_need, rrif_balance, non_reg_balance, tfsa_balance,
            other_taxable_income, age, province, year, is_rrif,
            meltdown_income_ceiling,
        )
    else:
        return _simple(spending_need, rrif_balance, non_reg_balance, tfsa_balance, age, is_rrif)


# ---------------------------------------------------------------------------
# Strategy 1: Simple (Phase 1 default — preserved for backward compatibility)
# ---------------------------------------------------------------------------

def _simple(
    spending_need: float,
    rrif_balance:  float,
    non_reg_balance: float,
    tfsa_balance:  float,
    age:           int,
    is_rrif:       bool,
) -> WithdrawalPlan:
    """RRIF first → Non-reg → TFSA. Same logic as Phase 1 cashflow."""
    rrif_min   = rrif_minimum_withdrawal(rrif_balance, age) if is_rrif else 0.0
    from_rrif  = max(rrif_min, min(spending_need, rrif_balance))
    rrif_min_applied = (rrif_min > spending_need)
    excess     = max(0.0, from_rrif - spending_need)

    remaining  = max(0.0, spending_need - from_rrif)
    from_non_reg = min(remaining, non_reg_balance)
    remaining  = max(0.0, remaining - from_non_reg)
    from_tfsa  = min(remaining, tfsa_balance)

    return WithdrawalPlan(
        from_rrif=round(from_rrif, 2),
        from_non_reg=round(from_non_reg, 2),
        from_tfsa=round(from_tfsa, 2),
        excess_to_non_reg=round(excess, 2),
        rrif_min_applied=rrif_min_applied,
        strategy_used=WithdrawalStrategy.SIMPLE,
    )


# ---------------------------------------------------------------------------
# Strategy 2: Bracket Fill
# ---------------------------------------------------------------------------

def _bracket_fill(
    spending_need:       float,
    rrif_balance:        float,
    non_reg_balance:     float,
    tfsa_balance:        float,
    other_taxable_income: float,
    age:                 int,
    province:            str,
    year:                int,
    is_rrif:             bool,
) -> WithdrawalPlan:
    """
    Fill each tax bracket from RRIF withdrawals before moving to non-reg or TFSA.

    Goal: keep total taxable income just below the next bracket ceiling.
    RRIF minimum is taken first. Then additional RRIF is drawn to fill the
    current bracket. Remaining spending need comes from non-reg (50% inclusion)
    then TFSA.

    The key insight: drawing from RRIF at 20.5% marginal is much better than
    letting the balance compound and being forced to draw at 26%+ later.
    """
    rrif_min = rrif_minimum_withdrawal(rrif_balance, age) if is_rrif else 0.0
    rrif_min_applied = False

    # Mandatory minimum first
    from_rrif = min(rrif_min, rrif_balance)
    current_taxable = other_taxable_income + from_rrif

    # Find the next bracket ceiling above current taxable income
    next_ceiling = _next_bracket_ceiling(current_taxable, province, year)

    # Fill up to that ceiling with additional RRIF withdrawals
    bracket_room = max(0.0, next_ceiling - current_taxable)
    additional_rrif = min(bracket_room, max(0.0, spending_need - from_rrif), rrif_balance - from_rrif)
    from_rrif += additional_rrif

    if rrif_min > spending_need:
        rrif_min_applied = True

    # Excess RRIF min beyond spending need → non-reg
    excess = max(0.0, from_rrif - spending_need)
    remaining = max(0.0, spending_need - from_rrif)

    # Non-reg for remaining gap (50% capital gains — less tax efficient per dollar
    # than RRIF at low brackets, but better than RRIF at high brackets)
    from_non_reg = min(remaining, non_reg_balance)
    remaining = max(0.0, remaining - from_non_reg)

    # TFSA last
    from_tfsa = min(remaining, tfsa_balance)

    return WithdrawalPlan(
        from_rrif=round(from_rrif, 2),
        from_non_reg=round(from_non_reg, 2),
        from_tfsa=round(from_tfsa, 2),
        excess_to_non_reg=round(excess, 2),
        rrif_min_applied=rrif_min_applied,
        strategy_used=WithdrawalStrategy.BRACKET_FILL,
    )


def _next_bracket_ceiling(current_taxable: float, province: str, year: int) -> float:
    """
    Return the upper bound of the next federal tax bracket above current_taxable.
    Used by bracket_fill to know how much more RRIF can be drawn at the same rate.
    """
    from agents.ori_rp.tax import _load_tax_brackets
    data     = _load_tax_brackets(year)
    brackets = data["federal"]["brackets"]
    bpa      = float(data["federal"]["basic_personal_amount"])
    taxable  = max(0.0, current_taxable - bpa)

    for bracket in brackets:
        lo = float(bracket["min"])
        hi = bracket.get("max")
        if hi is None:
            return current_taxable + 200_000  # effectively no ceiling at top bracket
        if taxable < float(hi):
            # We are in this bracket — ceiling is hi + bpa (gross income equivalent)
            return float(hi) + bpa

    return current_taxable + 200_000


# ---------------------------------------------------------------------------
# Strategy 3: RRSP Meltdown
# ---------------------------------------------------------------------------

def _rrsp_meltdown(
    spending_need:           float,
    rrif_balance:            float,
    non_reg_balance:         float,
    tfsa_balance:            float,
    other_taxable_income:    float,
    age:                     int,
    province:                str,
    year:                    int,
    is_rrif:                 bool,
    meltdown_income_ceiling: float | None,
) -> WithdrawalPlan:
    """
    Accelerate RRSP/RRIF withdrawals up to a target taxable income ceiling.

    This is optimal in low-income years (e.g. 60–64: before CPP/OAS and before
    RRIF forces large minimums at 72+). Withdraw now at 20.5% rather than later
    at 33%+.

    meltdown_income_ceiling defaults to $114,750 (top of 2nd federal bracket 2026).
    You can set it lower (e.g. $57,375) to stay in the 15% bracket.
    """
    if meltdown_income_ceiling is None:
        meltdown_income_ceiling = 114_750.0  # top of 2nd federal bracket 2026

    rrif_min = rrif_minimum_withdrawal(rrif_balance, age) if is_rrif else 0.0
    rrif_min_applied = False

    # Always take at least the RRIF minimum
    from_rrif = min(rrif_min, rrif_balance)
    current_taxable = other_taxable_income + from_rrif

    # Meltdown: draw RRIF up to income ceiling regardless of spending need.
    # The excess beyond spending goes to non_reg (forced tax-efficient savings).
    ceiling_room = max(0.0, meltdown_income_ceiling - current_taxable)
    meltdown_draw = min(ceiling_room, rrif_balance - from_rrif)
    from_rrif += meltdown_draw

    if rrif_min > spending_need:
        rrif_min_applied = True

    excess    = max(0.0, from_rrif - spending_need)
    remaining = max(0.0, spending_need - from_rrif)

    # Non-reg for any remaining spending gap
    from_non_reg = min(remaining, non_reg_balance)
    remaining    = max(0.0, remaining - from_non_reg)

    # TFSA last
    from_tfsa = min(remaining, tfsa_balance)

    return WithdrawalPlan(
        from_rrif=round(from_rrif, 2),
        from_non_reg=round(from_non_reg, 2),
        from_tfsa=round(from_tfsa, 2),
        excess_to_non_reg=round(excess, 2),
        rrif_min_applied=rrif_min_applied,
        strategy_used=WithdrawalStrategy.RRSP_MELTDOWN,
    )


# ---------------------------------------------------------------------------
# Tax comparison utility
# ---------------------------------------------------------------------------

def compare_withdrawal_strategies(
    spending_need:       float,
    rrif_balance:        float,
    non_reg_balance:     float,
    tfsa_balance:        float,
    other_taxable_income: float,
    age:                 int,
    province:            str = "ON",
    year:                int = 2026,
    is_rrif:             bool = False,
) -> list[dict]:
    """
    Run all three strategies for a single year and return the estimated tax
    for each. Used by the UI to show the benefit of tax-optimized sequencing.

    Returns list of dicts, one per strategy:
        strategy, from_rrif, from_non_reg, from_tfsa,
        taxable_income, estimated_tax, effective_rate_pct
    """
    rows = []
    for strat in WithdrawalStrategy:
        plan = plan_withdrawal(
            spending_need, rrif_balance, non_reg_balance, tfsa_balance,
            other_taxable_income, age, province, year, strategy=strat, is_rrif=is_rrif,
        )
        # Taxable income: RRIF withdrawals + other_taxable + 50% of non-reg
        taxable = (
            other_taxable_income
            + plan.from_rrif
            + plan.from_non_reg * 0.5
        )
        tax_result = estimate_tax(taxable, province=province, year=year)
        rows.append({
            "strategy":          strat.value,
            "from_rrif":         plan.from_rrif,
            "from_non_reg":      plan.from_non_reg,
            "from_tfsa":         plan.from_tfsa,
            "taxable_income":    round(taxable, 2),
            "estimated_tax":     tax_result["total_tax"],
            "effective_rate_pct": tax_result["effective_rate_pct"],
        })
    return rows


# ---------------------------------------------------------------------------
# TFSA room tracker
# ---------------------------------------------------------------------------

def compute_tfsa_room(
    tfsa_room_remaining:  float,
    tfsa_withdrawals_this_year: float = 0.0,
    tfsa_contributions_this_year: float = 0.0,
    current_year: int = 2026,
) -> dict:
    """
    Track TFSA room after withdrawals and contributions.

    CRA rule: withdrawals in year N restore room on January 1 of year N+1.
    So withdrawals this year increase *next* year's room, not current year.

    Returns
    -------
    dict:
        room_now          : float  — remaining room this year after contributions
        room_next_year    : float  — room available Jan 1 next year (+ restored)
        over_contribution : bool   — True if contributions exceed room_now
        annual_limit      : float  — new room added this year (from YAML)
    """
    from pathlib import Path
    import yaml
    refs_dir = Path(__file__).parent.parent.parent / "refs" / "retirement"
    path = refs_dir / "tfsa_room_by_year.yaml"
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
        annual_limit = float(data["annual_limit"].get(current_year, 7000))
    except Exception:
        annual_limit = 7000.0

    room_now  = tfsa_room_remaining - tfsa_contributions_this_year
    over      = room_now < 0
    room_next = max(0.0, room_now) + tfsa_withdrawals_this_year + annual_limit

    return {
        "room_now":          round(room_now,  2),
        "room_next_year":    round(room_next, 2),
        "over_contribution": over,
        "annual_limit":      annual_limit,
    }
