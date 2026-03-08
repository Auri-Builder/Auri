"""
agents/ori_wb/optimizer.py
--------------------------
RRSP vs TFSA contribution optimizer.

Core decision logic:
  - If marginal tax rate NOW > expected marginal rate IN RETIREMENT → RRSP preferred
    (tax deduction today worth more than tax-free growth alone)
  - If marginal rate now ≤ expected retirement rate → TFSA preferred
    (tax-free growth + tax-free withdrawal beats RRSP if rates cross)
  - Bracket-edge optimisation: RRSP contributions that push income below a bracket
    boundary get extra value; remainder goes to TFSA.

Reference:
  - Tax brackets loaded from refs/retirement/tax_brackets_{year}.yaml (reuses ori_rp data)
  - RRSP/TFSA limits from refs/wealth/contribution_limits.yaml

Disclaimer: Simplified marginal-rate model only. Does not account for OAS clawback,
income-splitting, pension income credit, dividend tax credits, or employer matching.
Consult a tax advisor before acting on these projections.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_REFS_RETIREMENT = Path(__file__).parent.parent.parent / "refs" / "retirement"
_REFS_WEALTH     = Path(__file__).parent.parent.parent / "refs" / "wealth"


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _load_tax_brackets(year: int) -> dict:
    import yaml
    path = _REFS_RETIREMENT / f"tax_brackets_{year}.yaml"
    if not path.exists():
        available = sorted(_REFS_RETIREMENT.glob("tax_brackets_*.yaml"), reverse=True)
        if not available:
            raise FileNotFoundError(f"No tax bracket files found in {_REFS_RETIREMENT}")
        path = available[0]
        logger.warning("optimizer: no brackets for %d, using %s", year, path.name)
    with path.open() as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def _load_contribution_limits() -> dict:
    import yaml
    path = _REFS_WEALTH / "contribution_limits.yaml"
    with path.open() as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Tax helpers
# ---------------------------------------------------------------------------

def _marginal_rate_at(income: float, province: str, year: int) -> float:
    """
    Return the combined federal + provincial marginal rate (0–1) at the
    top dollar of the given income, after basic personal amounts.
    """
    data = _load_tax_brackets(year)
    fed  = data.get("federal",  {})
    prov = data.get(province.upper(), data.get("BC", {}))

    def _top_rate(brackets: list[dict], bpa: float) -> float:
        taxable = max(0.0, income - bpa)
        if taxable <= 0:
            return 0.0
        for b in reversed(brackets):
            lo = float(b["min"])
            if taxable > lo:
                return float(b["rate"]) / 100.0
        return 0.0

    fed_rate  = _top_rate(fed.get("brackets", []),  float(fed.get("basic_personal_amount", 16_129)))
    prov_rate = _top_rate(prov.get("brackets", []), float(prov.get("basic_personal_amount", 11_981)))
    return min(fed_rate + prov_rate, 0.65)


def _total_tax(income: float, province: str, year: int) -> float:
    """Compute total combined tax on the given income."""
    data = _load_tax_brackets(year)
    fed  = data.get("federal",  {})
    prov = data.get(province.upper(), data.get("BC", {}))

    def _tax(brackets: list[dict], bpa: float) -> float:
        taxable = max(0.0, income - bpa)
        total = 0.0
        for b in brackets:
            lo   = float(b["min"])
            hi   = b["max"]
            rate = float(b["rate"]) / 100.0
            if taxable <= lo:
                break
            upper = float(hi) if hi is not None else taxable
            total += (min(taxable, upper) - lo) * rate
        return total

    return (
        _tax(fed.get("brackets",  []), float(fed.get("basic_personal_amount",  16_129))) +
        _tax(prov.get("brackets", []), float(prov.get("basic_personal_amount", 11_981)))
    )


# ---------------------------------------------------------------------------
# RRSP room helpers
# ---------------------------------------------------------------------------

def rrsp_new_room(earned_income: float, year: int) -> float:
    """New RRSP room earned for the given prior-year earned income and year."""
    limits = _load_contribution_limits()
    dollar_max = float(limits["rrsp_dollar_max"].get(year, 33_310))
    return min(earned_income * 0.18, dollar_max)


def tfsa_cumulative_room(birth_year: int, current_year: int) -> float:
    """
    Cumulative TFSA room for someone who turned 18 in birth_year+18.
    Counts from the later of 2009 or the year they turned 18.
    """
    limits    = _load_contribution_limits()
    annual    = limits["tfsa_annual_room"]
    eligible_from = max(2009, birth_year + 18)
    return float(sum(
        v for yr, v in annual.items()
        if eligible_from <= int(yr) <= current_year
    ))


# ---------------------------------------------------------------------------
# Core optimiser
# ---------------------------------------------------------------------------

@dataclass
class OptimizerInput:
    gross_income:            float          # current annual employment/self-employment income
    savings_available:       float          # amount available to contribute this year
    rrsp_room_remaining:     float          # carry-forward + new room (user-provided or computed)
    tfsa_room_remaining:     float          # user-provided remaining room
    province:                str   = "BC"
    current_year:            int   = 2026
    expected_retirement_income: float = 50_000  # estimated gross income in retirement (for marginal rate comparison)
    growth_rate:             float = 0.06   # assumed annual return (nominal)
    years_to_retirement:     int   = 20


@dataclass
class OptimizerResult:
    recommended_rrsp:        float   # recommended RRSP contribution
    recommended_tfsa:        float   # recommended TFSA contribution
    rationale:               str     # plain-English explanation
    marginal_rate_now:       float   # combined marginal rate today (0–1)
    marginal_rate_retirement: float  # expected combined marginal rate in retirement (0–1)
    rrsp_tax_saving:         float   # immediate tax refund from RRSP contribution
    rrsp_future_value:       float   # projected after-tax value of RRSP at retirement
    tfsa_future_value:       float   # projected value of TFSA at retirement (tax-free)
    rrsp_capped_by_room:     bool    # True if RRSP recommendation hit the room ceiling
    tfsa_capped_by_room:     bool    # True if TFSA recommendation hit the room ceiling
    surplus_unregistered:    float   # amount that exceeds both account rooms


def optimise(inp: OptimizerInput) -> OptimizerResult:
    """
    Determine optimal RRSP vs TFSA split for the given savings amount.

    Strategy
    --------
    1. Compute marginal rate today and expected marginal rate in retirement.
    2. If rate_now > rate_retirement: RRSP is preferred up to available room.
       Additionally check for bracket-edge opportunities (partial RRSP to
       drop to a lower bracket, remainder to TFSA).
    3. If rate_now <= rate_retirement: TFSA is preferred up to available room.
    4. Overflow (beyond both rooms) noted as non-registered.
    """
    year = inp.current_year
    rate_now = _marginal_rate_at(inp.gross_income, inp.province, year)
    rate_ret = _marginal_rate_at(inp.expected_retirement_income, inp.province, year)

    n    = inp.years_to_retirement
    g    = 1.0 + inp.growth_rate
    savings = inp.savings_available
    rrsp_room = inp.rrsp_room_remaining
    tfsa_room = inp.tfsa_room_remaining

    # ── Bracket-edge check ─────────────────────────────────────────────────
    # Find amount of RRSP contribution that would drop income to the next
    # lower bracket threshold (if any), giving a higher effective deduction.
    bracket_edge_rrsp = _bracket_edge_contribution(inp.gross_income, inp.province, year)

    # ── Decision ──────────────────────────────────────────────────────────
    rrsp_contrib = 0.0
    tfsa_contrib = 0.0

    if rate_now > rate_ret:
        # RRSP preferred — fill RRSP first, then TFSA
        rrsp_contrib = min(savings, rrsp_room)
        tfsa_contrib = min(savings - rrsp_contrib, tfsa_room)
        if bracket_edge_rrsp > 0 and bracket_edge_rrsp < rrsp_contrib:
            # Already going into RRSP past the edge; no change needed
            pass
        rationale = (
            f"Your marginal rate today ({rate_now:.1%}) exceeds your estimated retirement "
            f"rate ({rate_ret:.1%}). RRSP contributions deliver an immediate tax deduction "
            f"worth more than the future tax cost on withdrawals."
        )
    elif rate_now < rate_ret:
        # TFSA preferred — fill TFSA first, then RRSP
        tfsa_contrib = min(savings, tfsa_room)
        rrsp_contrib = min(savings - tfsa_contrib, rrsp_room)
        rationale = (
            f"Your estimated retirement marginal rate ({rate_ret:.1%}) exceeds your rate "
            f"today ({rate_now:.1%}). TFSA contributions avoid tax on withdrawals when your "
            f"rate will be higher."
        )
    else:
        # Equal rates — slight TFSA preference (no mandatory withdrawals, more flexible)
        if bracket_edge_rrsp > 0 and bracket_edge_rrsp <= savings and bracket_edge_rrsp <= rrsp_room:
            # Capture the bracket-edge benefit with a small RRSP top-up
            rrsp_contrib = bracket_edge_rrsp
            tfsa_contrib = min(savings - rrsp_contrib, tfsa_room)
            rationale = (
                f"Marginal rates are equal ({rate_now:.1%}). Contributing ${bracket_edge_rrsp:,.0f} "
                f"to RRSP captures a bracket-edge benefit; remainder goes to TFSA for flexibility."
            )
        else:
            tfsa_contrib = min(savings, tfsa_room)
            rrsp_contrib = min(savings - tfsa_contrib, rrsp_room)
            rationale = (
                f"Marginal rates are roughly equal ({rate_now:.1%}). TFSA is preferred for "
                f"flexibility — no mandatory withdrawals and simpler estate planning."
            )

    surplus = max(0.0, savings - rrsp_contrib - tfsa_contrib)

    # ── Projections ────────────────────────────────────────────────────────
    rrsp_tax_saving = rrsp_contrib * rate_now
    # RRSP: grows tax-deferred, taxed at retirement rate on withdrawal
    rrsp_fv_gross = rrsp_contrib * (g ** n)
    rrsp_fv       = rrsp_fv_gross * (1.0 - rate_ret)
    # TFSA: grows tax-free
    tfsa_fv       = tfsa_contrib * (g ** n)

    return OptimizerResult(
        recommended_rrsp          = round(rrsp_contrib, 2),
        recommended_tfsa          = round(tfsa_contrib, 2),
        rationale                 = rationale,
        marginal_rate_now         = rate_now,
        marginal_rate_retirement  = rate_ret,
        rrsp_tax_saving           = round(rrsp_tax_saving, 2),
        rrsp_future_value         = round(rrsp_fv, 2),
        tfsa_future_value         = round(tfsa_fv, 2),
        rrsp_capped_by_room       = (rrsp_contrib >= rrsp_room and savings > rrsp_room),
        tfsa_capped_by_room       = (tfsa_contrib >= tfsa_room and (savings - rrsp_contrib) > tfsa_room),
        surplus_unregistered      = round(surplus, 2),
    )


def _bracket_edge_contribution(income: float, province: str, year: int) -> float:
    """
    Return the RRSP contribution that would just reduce income to the next
    lower combined bracket threshold, or 0 if already at the bottom.
    """
    data  = _load_tax_brackets(year)
    fed   = data.get("federal", {})
    prov  = data.get(province.upper(), data.get("BC", {}))
    bpa_f = float(fed.get("basic_personal_amount",  16_129))
    bpa_p = float(prov.get("basic_personal_amount", 11_981))

    taxable_f = max(0.0, income - bpa_f)
    taxable_p = max(0.0, income - bpa_p)

    # Find next lower bracket boundary in both federal and provincial
    thresholds = set()
    for b in fed.get("brackets", []):
        lo = float(b["min"]) + bpa_f
        if 0 < lo < income:
            thresholds.add(lo)
    for b in prov.get("brackets", []):
        lo = float(b["min"]) + bpa_p
        if 0 < lo < income:
            thresholds.add(lo)

    if not thresholds:
        return 0.0
    # Nearest threshold just below income
    target = max(t for t in thresholds if t < income)
    return income - target
