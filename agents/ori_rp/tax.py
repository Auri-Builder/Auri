"""
agents/ori_rp/tax.py
---------------------
Canadian marginal tax estimation for retirement planning.

IMPORTANT: These are simplified estimates only.
- Brackets are loaded from refs/retirement/tax_brackets_{year}.yaml.
- Does not model surtaxes (ON), credits (age amount, pension income credit,
  dividend tax credits), AMT, or other personal circumstances.
- OAS clawback is computed separately and added to effective tax.
- Results are for planning purposes only — not for tax filing.

Disclaimer: These projections are estimates only. Tax calculations use simplified
marginal brackets and do not account for all deductions, credits, or personal
circumstances. Consult your tax advisor before acting on any figure in this tool.
"""

from __future__ import annotations

import logging
from pathlib import Path
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

_REFS_DIR = Path(__file__).parent.parent.parent / "refs" / "retirement"


# ---------------------------------------------------------------------------
# Reference data loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _load_tax_brackets(year: int) -> dict:
    """Load tax bracket YAML for the given year. Cached after first load."""
    path = _REFS_DIR / f"tax_brackets_{year}.yaml"
    if not path.exists():
        # Fall back to most recent available year
        available = sorted(_REFS_DIR.glob("tax_brackets_*.yaml"), reverse=True)
        if not available:
            raise FileNotFoundError(f"No tax bracket files found in {_REFS_DIR}")
        path = available[0]
        logger.warning("tax.py: no brackets for %d, using %s", year, path.name)

    import yaml
    with path.open() as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Core marginal tax computation
# ---------------------------------------------------------------------------

def _marginal_tax(income: float, brackets: list[dict], basic_personal: float) -> float:
    """
    Compute total tax on taxable income using progressive brackets.

    Parameters
    ----------
    income         : gross taxable income (before basic personal amount deduction)
    brackets       : list of {min, max, rate} dicts (rate in percent)
    basic_personal : basic personal amount deduction (reduces taxable income)

    Returns
    -------
    Tax payable as a dollar amount (≥ 0).
    """
    taxable = max(0.0, income - basic_personal)
    total_tax = 0.0
    for bracket in brackets:
        lo   = float(bracket["min"])
        hi   = bracket["max"]
        rate = float(bracket["rate"]) / 100.0

        if taxable <= lo:
            break
        upper = float(hi) if hi is not None else taxable
        amount_in_bracket = min(taxable, upper) - lo
        if amount_in_bracket > 0:
            total_tax += amount_in_bracket * rate

    return round(max(0.0, total_tax), 2)


def estimate_tax(
    income: float,
    province: str = "ON",
    year: int = 2026,
) -> dict:
    """
    Estimate combined federal + provincial income tax on the given income.

    Parameters
    ----------
    income   : total taxable income for the year (RRIF/RRSP withdrawals, CPP, OAS,
               non-reg interest/dividends, part-time income, etc.)
    province : two-letter province code (default "ON")
    year     : tax year — used to select the bracket file

    Returns
    -------
    dict:
        federal_tax          : float
        provincial_tax       : float
        total_tax            : float
        effective_rate_pct   : float   (total_tax / income * 100, or 0 if income=0)
        marginal_rate_pct    : float   (top bracket rate federal + provincial)
        province             : str
        year                 : int
        disclaimer           : str
    """
    if income <= 0:
        return {
            "federal_tax":        0.0,
            "provincial_tax":     0.0,
            "total_tax":          0.0,
            "effective_rate_pct": 0.0,
            "marginal_rate_pct":  0.0,
            "province":           province,
            "year":               year,
            "disclaimer":         _DISCLAIMER,
        }

    data     = _load_tax_brackets(year)
    fed      = data["federal"]
    prov_key = province.upper()
    prov     = data.get("provincial", {}).get(prov_key)

    if prov is None:
        logger.warning("tax.py: no provincial brackets for %s, using federal only", province)
        prov = {"basic_personal_amount": 0, "brackets": []}

    fed_tax  = _marginal_tax(income, fed["brackets"],  fed["basic_personal_amount"])
    prov_tax = _marginal_tax(income, prov["brackets"], prov["basic_personal_amount"])
    total    = round(fed_tax + prov_tax, 2)

    effective_pct = round(total / income * 100, 2) if income > 0 else 0.0

    # Marginal rate: top bracket hit at this income level
    marginal_fed  = _top_bracket_rate(income, fed["brackets"],  fed["basic_personal_amount"])
    marginal_prov = _top_bracket_rate(income, prov["brackets"], prov["basic_personal_amount"])

    return {
        "federal_tax":        fed_tax,
        "provincial_tax":     prov_tax,
        "total_tax":          total,
        "effective_rate_pct": effective_pct,
        "marginal_rate_pct":  round(marginal_fed + marginal_prov, 2),
        "province":           prov_key,
        "year":               year,
        "disclaimer":         _DISCLAIMER,
    }


def _top_bracket_rate(income: float, brackets: list[dict], basic_personal: float) -> float:
    """Return the marginal rate (%) applicable at the top of taxable income."""
    taxable = max(0.0, income - basic_personal)
    top_rate = 0.0
    for bracket in brackets:
        lo = float(bracket["min"])
        if taxable > lo:
            top_rate = float(bracket["rate"])
    return top_rate


# ---------------------------------------------------------------------------
# OAS clawback
# ---------------------------------------------------------------------------

def compute_oas_clawback(
    net_income: float,
    oas_received: float,
    year: int = 2026,
) -> dict:
    """
    Estimate OAS clawback (recovery tax) for the given net income.

    The clawback is 15% of net income above the threshold, but cannot
    exceed the OAS received. The clawback appears as a separate tax.

    Returns
    -------
    dict:
        clawback_amount   : float   (dollars clawed back)
        clawback_rate_pct : float   (effective clawback as % of OAS)
        threshold         : float
        net_oas           : float   (OAS after clawback)
    """
    data      = _load_tax_brackets(year)
    threshold = float(data["federal"]["oas_clawback_threshold"])
    rate      = float(data["federal"]["oas_clawback_rate"])

    excess    = max(0.0, net_income - threshold)
    clawback  = min(excess * rate, oas_received)
    net_oas   = max(0.0, oas_received - clawback)

    return {
        "clawback_amount":   round(clawback, 2),
        "clawback_rate_pct": round(clawback / oas_received * 100, 1) if oas_received else 0.0,
        "threshold":         threshold,
        "net_oas":           round(net_oas, 2),
    }


# ---------------------------------------------------------------------------
# RRIF minimum withdrawal
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_rrif_minimums() -> dict[int, float]:
    """Load RRIF minimum withdrawal % table. Returns {age: pct}."""
    path = _REFS_DIR / "rrif_minimums.yaml"
    import yaml
    with path.open() as f:
        data = yaml.safe_load(f)
    return {int(k): float(v) for k, v in data["minimums"].items()}


def rrif_minimum_pct(age: int) -> float:
    """
    Return the CRA prescribed RRIF minimum withdrawal percentage for the given age.

    Ages below 55 return 0 (no minimum applies before RRIF conversion).
    Ages above 95 return 20.0 (CRA cap).
    """
    table = _load_rrif_minimums()
    if age < 55:
        return 0.0
    if age >= 95:
        return table.get(95, 20.0)
    # Interpolate between known age entries
    if age in table:
        return table[age]
    # If exact age missing, walk down
    for a in range(age, 54, -1):
        if a in table:
            return table[a]
    return 0.0


def rrif_minimum_withdrawal(balance: float, age: int) -> float:
    """
    Compute the minimum dollar withdrawal from a RRIF for a given balance and age.

    Parameters
    ----------
    balance : RRIF balance at January 1
    age     : owner's age at January 1 of the withdrawal year

    Returns
    -------
    Minimum withdrawal in dollars (0 if age < 72 or balance <= 0).
    """
    if age < 72 or balance <= 0:
        return 0.0
    pct = rrif_minimum_pct(age)
    return round(balance * pct / 100.0, 2)


# ---------------------------------------------------------------------------
# Disclaimer
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "These projections are estimates only. Tax calculations use simplified marginal "
    "brackets and do not account for all deductions, credits, or personal circumstances. "
    "Consult your tax advisor, financial planner, and investment professional before "
    "acting on any projection in this tool."
)
