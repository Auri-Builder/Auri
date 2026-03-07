"""
agents/ori_rp/cashflow.py
--------------------------
Year-by-year retirement cash flow projection engine for the ORI Retirement Planner.

Design principles
-----------------
- Pure functions only — no I/O, no Streamlit, no network calls.
- All inputs come from retirement_profile.yaml (loaded by the caller).
- All personal data stays local and is never committed to git.
- Supports both single-person and household (primary + spouse) plans.
- Withdrawal strategy is selectable per scenario (Phase 2):
    SIMPLE        — RRIF first, then non-reg, then TFSA
    BRACKET_FILL  — draw RRIF to fill current bracket before switching accounts
    RRSP_MELTDOWN — accelerate RRIF in low-income years up to a taxable ceiling

Key RRIF rule applied here:
  - RRSP converts to RRIF at the end of the year the owner turns 71.
  - Starting at age 72, CRA-prescribed minimum withdrawals are mandatory.
  - If minimum exceeds spending need from RRIF, excess flows to non-registered.

Disclaimer: These projections are estimates only. Tax calculations use simplified
marginal brackets and do not account for all deductions, credits, or personal
circumstances. Consult your tax advisor, financial planner, and investment
professional before acting on any projection in this tool. CPP and OAS benefit
calculations are illustrative — use your My Service Canada statement for accurate
figures.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import functools
import pathlib

import yaml

from agents.ori_rp.tax import estimate_tax, rrif_minimum_withdrawal, compute_oas_clawback
from agents.ori_rp.cpp_oas import cpp_annual_benefit, oas_annual_benefit
from agents.ori_rp.withdrawal import WithdrawalStrategy, plan_withdrawal

_REFS_DIR = pathlib.Path(__file__).parent.parent.parent / "refs" / "retirement"


@functools.lru_cache(maxsize=1)
def _load_tfsa_limits() -> dict[int, int]:
    path = _REFS_DIR / "tfsa_room_by_year.yaml"
    with path.open() as f:
        data = yaml.safe_load(f)
    return {int(k): int(v) for k, v in data["annual_limit"].items()}


def _annual_tfsa_limit(year: int) -> int:
    """Return the CRA TFSA annual contribution limit for a given year.
    Falls back to the most recent known value for future years."""
    limits = _load_tfsa_limits()
    if year in limits:
        return limits[year]
    return limits[max(limits)]

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "These projections are estimates only. Tax calculations use simplified marginal "
    "brackets and do not account for all deductions, credits, or personal circumstances. "
    "Consult your tax advisor, financial planner, and investment professional before "
    "acting on any projection in this tool. CPP and OAS benefit calculations are "
    "illustrative — use your My Service Canada statement for accurate figures."
)


# ---------------------------------------------------------------------------
# Scenario parameters
# ---------------------------------------------------------------------------

@dataclass
class ScenarioParams:
    """Parameters for a single retirement projection run."""

    name: str = "Base Case"

    # Timing
    retirement_age:   int   = 65    # primary person's age when drawdown begins
    longevity_age:    int   = 95    # planning horizon (age to project to)

    # Spending
    target_annual_spending:      float = 80_000.0   # real dollars, today's purchasing power
    voluntary_tfsa_topup:        float = 0.0         # annual voluntary TFSA contribution (real $)
    inflation_rate_pct:          float = 2.5

    # Returns (real, after fees, after inflation)
    portfolio_return_pct: float = 5.0

    # Government income — start ages
    cpp_start_age: int = 65
    oas_start_age: int = 65

    # Part-time bridge income (real dollars)
    part_time_income:    float = 0.0
    part_time_until_age: int   = 0    # 0 = no bridge income

    # One-time large expenditures: [{year: int, amount: float, label: str}]
    large_expenditures: list[dict] = field(default_factory=list)

    # Province for tax estimation
    province: str = "ON"

    # Tax year for bracket lookup (normally current year — advances each year in projection)
    base_tax_year: int = 2026

    # Phase 2: withdrawal sequencing strategy
    withdrawal_strategy: WithdrawalStrategy = WithdrawalStrategy.SIMPLE

    # Phase 2: RRSP meltdown — target taxable income ceiling (None = 2nd federal bracket top)
    meltdown_income_ceiling: float | None = None

    # Per-person CPP/OAS start ages (0 = use the household cpp_start_age / oas_start_age)
    sp_cpp_start_age: int = 0
    sp_oas_start_age: int = 0

    # When True, RRIF minimum excess in retirement is sheltered in TFSA (up to room) before non_reg
    auto_tfsa_routing: bool = True


@dataclass
class PersonProfile:
    """Financial profile for one person (primary or spouse)."""

    current_age:             int
    rrsp_rrif_balance:       float
    tfsa_balance:            float
    non_registered_balance:  float
    cpp_monthly_at_65:       float
    oas_monthly_at_65:       float
    pension_monthly:         float = 0.0
    pension_start_age:       int   = 0    # 0 = already started / starts at retirement_age
    tfsa_room_remaining:     float = 0.0
    part_time_income:        float = 0.0
    part_time_until_age:     int   = 0
    province:                str   = "ON"


# ---------------------------------------------------------------------------
# Year-level result
# ---------------------------------------------------------------------------

@dataclass
class YearResult:
    """Projection output for a single calendar year."""

    year:               int
    age_primary:        int
    age_spouse:         int | None

    # Income sources (real dollars)
    cpp_income:         float
    oas_income:         float
    pension_income:     float
    part_time_income:   float
    portfolio_withdrawal: float   # total: sum of the three below
    withdrawal_from_rrif:    float   # taxable RRSP/RRIF withdrawal
    withdrawal_from_non_reg: float   # non-registered (50% cap-gains inclusion)
    withdrawal_from_tfsa:    float   # tax-free

    # Account balances (start of year, before withdrawal)
    rrsp_rrif_balance:      float
    tfsa_balance:           float
    non_reg_balance:        float

    # Tax
    gross_income:           float
    taxes_estimated:        float
    oas_clawback:           float

    # Spending
    spending_target:        float     # inflation-adjusted target for this year
    large_expenditure:      float     # one-time expenditure in this year (if any)
    spending_delivered:     float     # actual spending funded
    surplus_shortfall:      float     # positive = surplus, negative = shortfall

    # Start-of-year household portfolio (before growth & withdrawal — used by Monte Carlo)
    portfolio_start:        float

    # End-of-year portfolio total
    portfolio_value:        float

    # Flags
    rrif_minimum_applied:   bool      # True if RRIF minimum forced extra withdrawal
    portfolio_depleted:     bool      # True if portfolio hit zero this year


# ---------------------------------------------------------------------------
# Core projection engine
# ---------------------------------------------------------------------------

def project_scenario(
    primary:  PersonProfile,
    params:   ScenarioParams,
    spouse:   PersonProfile | None = None,
) -> list[YearResult]:
    """
    Run a year-by-year retirement cash flow projection.

    Parameters
    ----------
    primary : PersonProfile
        The primary investor's current financial state.
    params  : ScenarioParams
        Scenario assumptions (spending, returns, CPP/OAS timing, etc.).
    spouse  : PersonProfile | None
        Spouse profile. When provided, spouse RRSP/RRIF/TFSA balances grow
        and are included in portfolio totals. Spouse government income starts
        at the same CPP/OAS ages as the primary (Phase 1 simplification;
        Phase 4 adds per-person government income timing).

    Returns
    -------
    list[YearResult] — one entry per year from today through longevity_age.
    """
    results: list[YearResult] = []

    # State — primary
    rrif     = primary.rrsp_rrif_balance
    tfsa     = primary.tfsa_balance
    non_reg  = primary.non_registered_balance
    is_rrif  = primary.current_age > 71   # already converted

    # State — spouse (if present)
    sp_rrif    = spouse.rrsp_rrif_balance      if spouse else 0.0
    sp_tfsa    = spouse.tfsa_balance            if spouse else 0.0
    sp_non_reg = spouse.non_registered_balance  if spouse else 0.0
    sp_is_rrif = (spouse.current_age > 71)      if spouse else False

    current_year = params.base_tax_year
    age_primary  = primary.current_age
    age_spouse   = spouse.current_age if spouse else None

    # Pre-compute real CPP/OAS annual amounts in today's dollars
    cpp_annual_primary = cpp_annual_benefit(primary.cpp_monthly_at_65, params.cpp_start_age)
    oas_annual_primary = oas_annual_benefit(primary.oas_monthly_at_65, params.oas_start_age)

    cpp_annual_spouse = 0.0
    oas_annual_spouse = 0.0
    if spouse:
        cpp_annual_spouse = cpp_annual_benefit(spouse.cpp_monthly_at_65, params.cpp_start_age)
        oas_annual_spouse = oas_annual_benefit(spouse.oas_monthly_at_65, params.oas_start_age)

    inflation   = params.inflation_rate_pct / 100.0
    ret_rate    = params.portfolio_return_pct / 100.0
    lump_by_yr  = {e["year"]: float(e.get("amount", 0)) for e in params.large_expenditures}

    # Track live TFSA room so pre-retirement surplus fills TFSA before non_reg
    tfsa_room    = primary.tfsa_room_remaining
    sp_tfsa_room = spouse.tfsa_room_remaining if spouse else 0.0

    while age_primary <= params.longevity_age:
        # ── Pre-retirement gate ───────────────────────────────────────────
        # Years before retirement_age are an accumulation phase:
        # no retirement spending is drawn; portfolio grows; RRIF minimums
        # still apply (mandatory regardless of retirement status); any
        # pension / part-time income earned pre-retirement flows to non_reg.
        in_retirement = age_primary >= params.retirement_age

        # ── Inflation-adjust spending target ──────────────────────────────
        years_from_base = current_year - params.base_tax_year
        inflation_factor = (1 + inflation) ** years_from_base

        # Add new TFSA room each January (year 0 room already in tfsa_room from profile)
        if years_from_base > 0:
            tfsa_room += _annual_tfsa_limit(current_year)
            if spouse:
                sp_tfsa_room += _annual_tfsa_limit(current_year)

        if in_retirement:
            spending_target = params.target_annual_spending * inflation_factor
            large_exp       = lump_by_yr.get(current_year, 0.0) * inflation_factor
            # Voluntary TFSA top-up is an additional annual draw (sheltered immediately in TFSA).
            # It is inflation-adjusted and added to the withdrawal need, then credited back
            # to the TFSA balance below — net effect is forced RRSP→TFSA transfer each year.
            tfsa_topup = params.voluntary_tfsa_topup * inflation_factor
        else:
            spending_target = 0.0
            large_exp       = 0.0
            tfsa_topup      = 0.0
        total_need = spending_target + large_exp + tfsa_topup

        # ── RRIF conversion ───────────────────────────────────────────────
        # Convert RRSP → RRIF at age 71
        if age_primary == 71:
            is_rrif = True
        if spouse and age_spouse == 71:
            sp_is_rrif = True

        # ── Government income (real then nominally inflated) ──────────────
        # Track per-person so taxes can be computed individually for households.
        p_cpp = cpp_annual_primary * inflation_factor if age_primary >= params.cpp_start_age else 0.0
        p_oas = oas_annual_primary * inflation_factor if age_primary >= params.oas_start_age else 0.0
        pension_start = primary.pension_start_age or params.retirement_age
        p_pension = primary.pension_monthly * 12 * inflation_factor if age_primary >= pension_start else 0.0
        p_pt = primary.part_time_income * inflation_factor if (
            primary.part_time_until_age > 0 and age_primary <= primary.part_time_until_age
        ) else 0.0

        sp_cpp = 0.0; sp_oas = 0.0; sp_pension = 0.0; sp_pt = 0.0
        if spouse:
            sp_cpp_age = params.sp_cpp_start_age if params.sp_cpp_start_age > 0 else params.cpp_start_age
            sp_oas_age = params.sp_oas_start_age if params.sp_oas_start_age > 0 else params.oas_start_age
            sp_cpp = cpp_annual_spouse * inflation_factor if age_spouse >= sp_cpp_age else 0.0
            sp_oas = oas_annual_spouse * inflation_factor if age_spouse >= sp_oas_age else 0.0
            sp_pension_start = spouse.pension_start_age or params.retirement_age
            sp_pension = spouse.pension_monthly * 12 * inflation_factor if age_spouse >= sp_pension_start else 0.0
            sp_pt = spouse.part_time_income * inflation_factor if (
                spouse.part_time_until_age > 0 and age_spouse <= spouse.part_time_until_age
            ) else 0.0

        cpp_income  = p_cpp  + sp_cpp
        oas_income  = p_oas  + sp_oas
        pension     = p_pension + sp_pension
        pt_income   = p_pt   + sp_pt

        p_guaranteed  = p_cpp  + p_oas  + p_pension  + p_pt
        sp_guaranteed = sp_cpp + sp_oas + sp_pension + sp_pt
        guaranteed_income = p_guaranteed + sp_guaranteed

        # ── RRIF minimum withdrawal ───────────────────────────────────────
        # Mandatory regardless of retirement status.
        rrif_min    = rrif_minimum_withdrawal(rrif,    age_primary) if is_rrif else 0.0
        sp_rrif_min = rrif_minimum_withdrawal(sp_rrif, age_spouse)  if (spouse and sp_is_rrif) else 0.0

        tax_year = int(min(params.base_tax_year + years_from_base, 2026))

        # ── Spouse withdrawals (tracked separately for per-person tax) ───
        sp_from_rrif    = 0.0
        sp_from_non_reg = 0.0
        sp_from_tfsa    = 0.0
        sp_excess_to_non_reg = 0.0

        if in_retirement:
            # ── Portfolio withdrawal needed (retirement years) ────────────
            income_gap = max(0.0, total_need - guaranteed_income)

            if spouse:
                # Split income_gap proportionally by each person's portfolio balance.
                # Each person draws from their own accounts → individual tax brackets.
                p_portfolio  = rrif    + non_reg    + tfsa
                sp_portfolio = sp_rrif + sp_non_reg + sp_tfsa
                household_portfolio = p_portfolio + sp_portfolio

                if household_portfolio > 0:
                    p_frac = p_portfolio / household_portfolio
                else:
                    p_frac = 0.5

                p_gap  = income_gap * p_frac
                sp_gap = income_gap * (1.0 - p_frac)

                # Primary withdrawal plan
                wp = plan_withdrawal(
                    spending_need=p_gap,
                    rrif_balance=rrif,
                    non_reg_balance=non_reg,
                    tfsa_balance=tfsa,
                    other_taxable_income=p_guaranteed,
                    age=age_primary,
                    province=params.province,
                    year=tax_year,
                    strategy=params.withdrawal_strategy,
                    is_rrif=is_rrif,
                    meltdown_income_ceiling=params.meltdown_income_ceiling,
                )

                # Spouse withdrawal plan
                sp_wp = plan_withdrawal(
                    spending_need=sp_gap,
                    rrif_balance=sp_rrif,
                    non_reg_balance=sp_non_reg,
                    tfsa_balance=sp_tfsa,
                    other_taxable_income=sp_guaranteed,
                    age=age_spouse,
                    province=params.province,
                    year=tax_year,
                    strategy=params.withdrawal_strategy,
                    is_rrif=sp_is_rrif,
                    meltdown_income_ceiling=params.meltdown_income_ceiling,
                )

                from_rrif        = wp.from_rrif
                from_non_reg     = wp.from_non_reg
                from_tfsa        = wp.from_tfsa
                rrif_min_applied = wp.rrif_min_applied or sp_wp.rrif_min_applied
                excess_to_non_reg = wp.excess_to_non_reg

                sp_from_rrif         = sp_wp.from_rrif
                sp_from_non_reg      = sp_wp.from_non_reg
                sp_from_tfsa         = sp_wp.from_tfsa
                sp_excess_to_non_reg = sp_wp.excess_to_non_reg

            else:
                # Single person — full gap from primary accounts
                wp = plan_withdrawal(
                    spending_need=income_gap,
                    rrif_balance=rrif,
                    non_reg_balance=non_reg,
                    tfsa_balance=tfsa,
                    other_taxable_income=p_guaranteed,
                    age=age_primary,
                    province=params.province,
                    year=tax_year,
                    strategy=params.withdrawal_strategy,
                    is_rrif=is_rrif,
                    meltdown_income_ceiling=params.meltdown_income_ceiling,
                )
                from_rrif        = wp.from_rrif
                from_non_reg     = wp.from_non_reg
                from_tfsa        = wp.from_tfsa
                rrif_min_applied = wp.rrif_min_applied
                excess_to_non_reg = wp.excess_to_non_reg

            total_from_rrif    = from_rrif    + sp_from_rrif
            total_from_non_reg = from_non_reg + sp_from_non_reg
            total_from_tfsa    = from_tfsa    + sp_from_tfsa

            portfolio_withdrawal = total_from_rrif + total_from_non_reg + total_from_tfsa
            spending_delivered   = min(total_need, guaranteed_income + portfolio_withdrawal)
            surplus_shortfall    = spending_delivered - total_need

            # Per-person taxable income (Canadian tax is individual, not joint)
            p_taxable  = p_guaranteed  + from_rrif    + from_non_reg    * 0.5
            sp_taxable = sp_guaranteed + sp_from_rrif + sp_from_non_reg * 0.5
            taxable_income = p_taxable + sp_taxable  # combined for reporting only

        else:
            # ── Accumulation phase (pre-retirement) ───────────────────────
            # No retirement spending; only mandatory RRIF minimums are taken.
            from_rrif         = rrif_min           # mandatory minimum only
            from_non_reg      = 0.0
            from_tfsa         = 0.0
            rrif_min_applied  = rrif_min > 0
            excess_to_non_reg = 0.0

            if sp_rrif_min > 0:
                sp_from_rrif = min(sp_rrif_min, sp_rrif)
                sp_from_non_reg = 0.0
                sp_from_tfsa    = 0.0

            portfolio_withdrawal = from_rrif + sp_from_rrif   # only mandatory minimums
            spending_delivered   = 0.0
            surplus_shortfall    = 0.0

            # Per-person taxable income for accumulation years
            p_taxable  = rrif_min  + p_guaranteed
            sp_taxable = sp_from_rrif + sp_guaranteed
            taxable_income = p_taxable + sp_taxable  # combined for reporting

        # ── Tax estimation (per-person for accuracy, then summed) ─────────
        p_tax_result  = estimate_tax(p_taxable,  province=params.province, year=tax_year)
        sp_tax_result = estimate_tax(sp_taxable, province=params.province, year=tax_year) if spouse else {"total_tax": 0.0}
        taxes = p_tax_result["total_tax"] + sp_tax_result["total_tax"]

        # OAS clawback — per person on their individual OAS
        p_clawback  = compute_oas_clawback(p_taxable,  p_oas,  year=tax_year)["clawback_amount"]
        sp_clawback = compute_oas_clawback(sp_taxable, sp_oas, year=tax_year)["clawback_amount"] if spouse else 0.0
        oas_clawback = p_clawback + sp_clawback
        taxes       += oas_clawback

        # ── Update balances — apply growth first, then withdrawals ────────
        # Growth applies to start-of-year balances before withdrawal
        rrif_growth    = rrif    * ret_rate
        non_reg_growth = non_reg * ret_rate
        tfsa_growth    = tfsa    * ret_rate

        sp_rrif_growth    = sp_rrif    * ret_rate if spouse else 0.0
        sp_non_reg_growth = sp_non_reg * ret_rate if spouse else 0.0
        sp_tfsa_growth    = sp_tfsa    * ret_rate if spouse else 0.0

        # Snapshot start-of-year balances for YearResult
        rrif_start    = rrif
        non_reg_start = non_reg
        tfsa_start    = tfsa
        household_start = rrif + non_reg + tfsa + (
            sp_rrif + sp_non_reg + sp_tfsa if spouse else 0.0
        )

        rrif     = max(0.0, rrif    + rrif_growth    - from_rrif)
        non_reg  = max(0.0, non_reg + non_reg_growth - from_non_reg)
        tfsa     = max(0.0, tfsa    + tfsa_growth    - from_tfsa)

        if spouse:
            sp_rrif    = max(0.0, sp_rrif    + sp_rrif_growth    - sp_from_rrif)
            sp_non_reg = max(0.0, sp_non_reg + sp_non_reg_growth - sp_from_non_reg)
            sp_tfsa    = max(0.0, sp_tfsa    + sp_tfsa_growth    - sp_from_tfsa)

        # RRIF minimum excess (retirement) → TFSA first (if auto_tfsa_routing), then non_reg
        if in_retirement and excess_to_non_reg > 0:
            if params.auto_tfsa_routing and tfsa_room > 0:
                to_tfsa_excess = min(excess_to_non_reg, tfsa_room)
                tfsa_room = max(0.0, tfsa_room - to_tfsa_excess)
                tfsa    += to_tfsa_excess
                non_reg += excess_to_non_reg - to_tfsa_excess
            else:
                non_reg += excess_to_non_reg
        if in_retirement and sp_excess_to_non_reg > 0:
            if params.auto_tfsa_routing and sp_tfsa_room > 0:
                sp_to_tfsa_excess = min(sp_excess_to_non_reg, sp_tfsa_room)
                sp_tfsa_room = max(0.0, sp_tfsa_room - sp_to_tfsa_excess)
                sp_tfsa    += sp_to_tfsa_excess
                sp_non_reg += sp_excess_to_non_reg - sp_to_tfsa_excess
            else:
                sp_non_reg += sp_excess_to_non_reg
        # Voluntary TFSA top-up: money was drawn from RRSP as part of total_need;
        # credit it back into TFSA (up to room). Split evenly between spouses.
        # Any overage beyond available room goes to non_reg.
        if in_retirement and tfsa_topup > 0:
            divisor = 2.0 if spouse else 1.0
            p_topup = tfsa_topup / divisor
            topup_to_tfsa = min(p_topup, tfsa_room)
            tfsa_room = max(0.0, tfsa_room - topup_to_tfsa)
            tfsa    += topup_to_tfsa
            non_reg += p_topup - topup_to_tfsa
            if spouse:
                sp_p_topup = tfsa_topup / divisor
                sp_topup_to_tfsa = min(sp_p_topup, sp_tfsa_room)
                sp_tfsa_room = max(0.0, sp_tfsa_room - sp_topup_to_tfsa)
                sp_tfsa    += sp_topup_to_tfsa
                sp_non_reg += sp_p_topup - sp_topup_to_tfsa

        if not in_retirement:
            # Pre-retirement surplus income: fill TFSA room first (tax-free growth),
            # spill remainder to non_reg.  TFSA withdrawals restore room Jan 1 of the
            # following year — modelled by the annual_limit increment above.
            to_tfsa   = min(guaranteed_income, tfsa_room)
            tfsa_room = max(0.0, tfsa_room - to_tfsa)
            tfsa    += to_tfsa
            non_reg += guaranteed_income - to_tfsa

        total_portfolio = rrif + non_reg + tfsa
        if spouse:
            total_portfolio += sp_rrif + sp_non_reg + sp_tfsa

        portfolio_depleted = in_retirement and (total_portfolio < 1.0)

        results.append(YearResult(
            year=current_year,
            age_primary=age_primary,
            age_spouse=age_spouse,
            cpp_income=round(cpp_income,         2),
            oas_income=round(oas_income,         2),
            pension_income=round(pension,        2),
            part_time_income=round(pt_income,    2),
            portfolio_withdrawal=round(portfolio_withdrawal,        2),
            withdrawal_from_rrif=round(from_rrif + sp_from_rrif,         2),
            withdrawal_from_non_reg=round(from_non_reg + sp_from_non_reg, 2),
            withdrawal_from_tfsa=round(from_tfsa + sp_from_tfsa,         2),
            rrsp_rrif_balance=round(rrif_start,  2),
            tfsa_balance=round(tfsa_start,       2),
            non_reg_balance=round(non_reg_start, 2),
            gross_income=round(taxable_income,   2),
            taxes_estimated=round(taxes,         2),
            oas_clawback=round(oas_clawback,     2),
            spending_target=round(spending_target, 2),
            large_expenditure=round(large_exp,   2),
            spending_delivered=round(spending_delivered, 2),
            surplus_shortfall=round(surplus_shortfall, 2),
            portfolio_start=round(household_start,  2),
            portfolio_value=round(total_portfolio, 2),
            rrif_minimum_applied=rrif_min_applied,
            portfolio_depleted=portfolio_depleted,
        ))

        # Continue projecting even after depletion to show shortfall years.

        age_primary += 1
        if age_spouse is not None:
            age_spouse += 1
        current_year += 1

    return results


# ---------------------------------------------------------------------------
# Scenario to JSON-serialisable dict
# ---------------------------------------------------------------------------

def scenario_to_dict(
    params:   ScenarioParams,
    results:  list[YearResult],
    generated_at: str | None = None,
) -> dict:
    """
    Convert a completed scenario run to a JSON-serialisable dict.
    Includes the disclaimer at the top level.

    Parameters
    ----------
    generated_at : ISO 8601 datetime string (e.g. "2026-03-06T14:32:00").
                   Defaults to current UTC time if None.
    """
    if generated_at is None:
        from datetime import datetime, timezone
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    return {
        "scenario_name": params.name,
        "generated_at":  generated_at,
        "disclaimer":    DISCLAIMER,
        "parameters": {
            "retirement_age":         params.retirement_age,
            "longevity_age":          params.longevity_age,
            "target_annual_spending": params.target_annual_spending,
            "inflation_rate_pct":     params.inflation_rate_pct,
            "portfolio_return_pct":   params.portfolio_return_pct,
            "cpp_start_age":          params.cpp_start_age,
            "oas_start_age":          params.oas_start_age,
            "part_time_income":       params.part_time_income,
            "part_time_until_age":    params.part_time_until_age,
            "province":               params.province,
            "large_expenditures":     params.large_expenditures,
        },
        "cash_flows": [
            {
                "year":                   r.year,
                "age_primary":            r.age_primary,
                "age_spouse":             r.age_spouse,
                "cpp_income":             r.cpp_income,
                "oas_income":             r.oas_income,
                "pension_income":         r.pension_income,
                "part_time_income":       r.part_time_income,
                "portfolio_withdrawal":      r.portfolio_withdrawal,
                "withdrawal_from_rrif":     r.withdrawal_from_rrif,
                "withdrawal_from_non_reg":  r.withdrawal_from_non_reg,
                "withdrawal_from_tfsa":     r.withdrawal_from_tfsa,
                "rrsp_rrif_balance":        r.rrsp_rrif_balance,
                "tfsa_balance":           r.tfsa_balance,
                "non_reg_balance":        r.non_reg_balance,
                "gross_income":           r.gross_income,
                "taxes_estimated":        r.taxes_estimated,
                "oas_clawback":           r.oas_clawback,
                "spending_target":        r.spending_target,
                "large_expenditure":      r.large_expenditure,
                "spending_delivered":     r.spending_delivered,
                "surplus_shortfall":      r.surplus_shortfall,
                "portfolio_value":        r.portfolio_value,
                "rrif_minimum_applied":   r.rrif_minimum_applied,
                "portfolio_depleted":     r.portfolio_depleted,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Summary stats from a scenario run
# ---------------------------------------------------------------------------

def scenario_summary(params: ScenarioParams, results: list[YearResult]) -> dict:
    """
    Compute top-level summary statistics from a completed scenario run.

    Returns
    -------
    dict:
        depletion_age      : int | None  — age at which portfolio first hits zero
        depletion_year     : int | None
        final_portfolio    : float       — value at longevity_age
        total_taxes        : float       — cumulative taxes over projection
        total_cpp_oas      : float       — cumulative government income
        peak_portfolio     : float       — highest portfolio value achieved
        total_withdrawals  : float       — cumulative portfolio withdrawals
        years_with_shortfall : int       — years where spending < target
    """
    depletion_age  = None
    depletion_year = None
    total_taxes    = 0.0
    total_cpp_oas  = 0.0
    peak_portfolio = 0.0
    total_withdrawals = 0.0
    shortfall_years   = 0

    coverage_ratios        = []
    first_undercoverage_age = None

    for r in results:
        total_taxes       += r.taxes_estimated
        total_cpp_oas     += r.cpp_income + r.oas_income
        total_withdrawals += r.portfolio_withdrawal
        if r.portfolio_value > peak_portfolio:
            peak_portfolio = r.portfolio_value
        if r.portfolio_depleted and depletion_age is None:
            depletion_age  = r.age_primary
            depletion_year = r.year
        if r.surplus_shortfall < -1.0:     # ignore sub-dollar rounding artefacts
            shortfall_years += 1

        # Coverage ratio — only count retirement years (spending_target > 0)
        if r.spending_target > 0:
            ratio = r.spending_delivered / r.spending_target
            coverage_ratios.append(ratio)
            if ratio < 0.9999 and first_undercoverage_age is None:
                first_undercoverage_age = r.age_primary

    avg_coverage_pct = (sum(coverage_ratios) / len(coverage_ratios) * 100) if coverage_ratios else 100.0
    min_coverage_pct = (min(coverage_ratios) * 100) if coverage_ratios else 100.0

    final = results[-1].portfolio_value if results else 0.0

    return {
        "depletion_age":          depletion_age,
        "depletion_year":         depletion_year,
        "final_portfolio":        round(final,             2),
        "total_taxes":            round(total_taxes,       2),
        "total_cpp_oas":          round(total_cpp_oas,     2),
        "peak_portfolio":         round(peak_portfolio,    2),
        "total_withdrawals":      round(total_withdrawals, 2),
        "years_with_shortfall":   shortfall_years,
        "avg_coverage_pct":       round(avg_coverage_pct,  1),
        "min_coverage_pct":       round(min_coverage_pct,  1),
        "first_undercoverage_age": first_undercoverage_age,
    }
