"""
agents/ori_rp/readiness.py
----------------------------
Retirement Readiness Score — Phase 4.

Produces a 0–100 composite score from five weighted components, each grounded
in the investor's actual profile and projection output rather than arbitrary
self-reported answers.

Components and weights
----------------------
1. Portfolio Longevity       40 pts
   Does the Base Case portfolio last to the planning horizon?
   Full 40 pts if it reaches longevity_age; proportional if it depletes earlier.

2. Income Coverage           25 pts
   Guaranteed income (CPP + OAS + pension) as a fraction of spending target.
   25 pts if guaranteed ≥ 100% of spending (portfolio is gravy).
   0 pts if guaranteed = 0%.

3. Monte Carlo Confidence    15 pts  (only if MC has been run; else estimated)
   Based on the probability-of-success from the MC simulation.
   15 pts at 90%+ success; 0 pts at 50% or below.

4. TFSA Utilization          10 pts
   TFSA balance relative to cumulative available room.
   Rewards having money in the most tax-efficient account.

5. Liquidity Buffer          10 pts
   Non-registered balance as a multiple of annual spending.
   2+ years of spending = full 10 pts; 0 years = 0 pts.

Score interpretation
---------------------
90–100 : Excellent — strongly on track
75–89  : Good — on track with minor gaps
60–74  : Fair — some attention needed
40–59  : At risk — significant planning gaps
< 40   : Critical — immediate action required
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Score thresholds
# ---------------------------------------------------------------------------

_LONGEVITY_WEIGHT  = 40
_COVERAGE_WEIGHT   = 25
_MC_WEIGHT         = 15
_TFSA_WEIGHT       = 10
_LIQUIDITY_WEIGHT  = 10

_SCORE_LABELS = [
    (90, "Excellent"),
    (75, "Good"),
    (60, "Fair"),
    (40, "At Risk"),
    (0,  "Critical"),
]


def score_label(score: float) -> str:
    for threshold, label in _SCORE_LABELS:
        if score >= threshold:
            return label
    return "Critical"


# ---------------------------------------------------------------------------
# Component scorers
# ---------------------------------------------------------------------------

def _longevity_score(summary: dict, longevity_age: int, current_age: int) -> tuple[float, str]:
    """40 pts — proportional to how many retirement years are funded."""
    dep_age = summary.get("depletion_age")

    if dep_age is None:
        return float(_LONGEVITY_WEIGHT), f"Portfolio projects to last through age {longevity_age}."

    # Measure funded years from depletion vs planning horizon, not from current age.
    # This avoids penalizing people who are still pre-retirement.
    total_years  = max(1, longevity_age - current_age)
    funded_years = max(0, dep_age - current_age)
    pts = round(_LONGEVITY_WEIGHT * funded_years / total_years, 1)
    return pts, (
        f"Portfolio projects to deplete at age {dep_age} "
        f"({funded_years} of {total_years} years funded)."
    )


def _income_coverage_score(
    guaranteed_annual: float,
    spending_target:   float,
) -> tuple[float, str]:
    """25 pts — how much of spending is covered by guaranteed income."""
    if spending_target <= 0:
        return float(_COVERAGE_WEIGHT), "No spending target set."

    ratio = min(1.0, guaranteed_annual / spending_target)
    pts   = round(_COVERAGE_WEIGHT * ratio, 1)
    pct   = ratio * 100

    if ratio >= 1.0:
        detail = f"Guaranteed income fully covers spending target ({pct:.0f}% coverage)."
    else:
        gap = spending_target - guaranteed_annual
        detail = (
            f"Guaranteed income covers {pct:.0f}% of spending target. "
            f"Gap of ${gap:,.0f}/yr must come from portfolio."
        )
    return pts, detail


def _mc_score(prob_success: float | None) -> tuple[float, str]:
    """15 pts — Monte Carlo probability of success (estimated if not run)."""
    if prob_success is None:
        # No MC run — estimate neutral (7.5 / 15)
        return 7.5, "Monte Carlo not yet run. Score estimated at 50%. Run MC for a precise figure."

    # 0 pts at 50% success, 15 pts at 90%+
    clamped = min(max(prob_success, 50.0), 90.0)
    pts = round(_MC_WEIGHT * (clamped - 50.0) / 40.0, 1)
    return pts, f"Monte Carlo probability of success: {prob_success:.1f}%."


def _tfsa_score(
    tfsa_balance:        float,
    tfsa_room_remaining: float,
    cumulative_room:     float = 102_000,
) -> tuple[float, str]:
    """10 pts — TFSA utilization (balance / total room ever available)."""
    total_room_used = cumulative_room - tfsa_room_remaining
    total_room      = cumulative_room

    if total_room <= 0:
        return float(_TFSA_WEIGHT), "TFSA room data unavailable."

    # Score based on fraction of lifetime room that holds a balance
    utilization = min(1.0, tfsa_balance / max(1.0, total_room_used)) if total_room_used > 0 else 0.0
    pts = round(_TFSA_WEIGHT * utilization, 1)

    if tfsa_room_remaining > 20_000:
        detail = (
            f"${tfsa_room_remaining:,.0f} in unused TFSA room. "
            "Consider maximizing TFSA contributions for tax-free growth."
        )
    else:
        detail = f"TFSA well-utilized. Balance: ${tfsa_balance:,.0f}."

    return pts, detail


def _liquidity_score(
    non_reg_balance: float,
    annual_spending: float,
) -> tuple[float, str]:
    """10 pts — non-registered balance as years of spending (0 yrs = 0, 2+ yrs = 10)."""
    if annual_spending <= 0:
        return float(_LIQUIDITY_WEIGHT), "No spending target set."

    years = non_reg_balance / annual_spending
    pts   = round(min(1.0, years / 2.0) * _LIQUIDITY_WEIGHT, 1)

    if years >= 2.0:
        detail = f"Non-registered balance covers {years:.1f} years of spending — strong liquidity buffer."
    elif years >= 1.0:
        detail = f"Non-registered balance covers {years:.1f} year of spending."
    else:
        detail = (
            f"Non-registered balance covers {years:.1f} years of spending. "
            "Limited liquidity outside registered accounts."
        )
    return pts, detail


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def compute_readiness_score(
    primary_age:         int,
    rrsp_rrif_balance:   float,
    tfsa_balance:        float,
    non_reg_balance:     float,
    tfsa_room_remaining: float,
    cpp_monthly_at_65:   float,
    oas_monthly_at_65:   float,
    pension_monthly:     float,
    cpp_start_age:       int,
    oas_start_age:       int,
    annual_spending:     float,
    province:            str,
    base_year:           int,
    longevity_age:       int = 95,
    mc_prob_success:     float | None = None,
    cumulative_tfsa_room: float = 102_000,
    spouse:              "PersonProfile | None" = None,
    sp_cpp_start_age:    int = 0,
    sp_oas_start_age:    int = 0,
) -> dict:
    """
    Compute the retirement readiness score (0–100) from profile data.

    A quick deterministic projection (Base Case: 5% return, 2.5% inflation,
    CPP/OAS at their planned start ages) is run internally to get the longevity
    summary. When a spouse is provided the projection uses both people's accounts
    against the full household spending target — giving an accurate longevity result.

    Parameters
    ----------
    mc_prob_success : If a Monte Carlo simulation has already been run, pass
                      the prob_success % here. Otherwise defaults to neutral 50%.
    spouse          : Spouse PersonProfile, if applicable. When provided all
                      household accounts and guaranteed income are included.

    Returns
    -------
    dict:
        score              : float   0–100
        label              : str     "Excellent" / "Good" / "Fair" / "At Risk" / "Critical"
        components         : list[dict]  per-component breakdown
        total_portfolio    : float   sum of all account balances (household)
        disclaimer         : str
    """
    from agents.ori_rp.cashflow import ScenarioParams, PersonProfile, project_scenario, scenario_summary
    from agents.ori_rp.cpp_oas import cpp_annual_benefit, oas_annual_benefit

    # Quick Base Case run — include spouse so the projection uses the full household portfolio
    primary = PersonProfile(
        current_age=primary_age,
        rrsp_rrif_balance=rrsp_rrif_balance,
        tfsa_balance=tfsa_balance,
        non_registered_balance=non_reg_balance,
        cpp_monthly_at_65=cpp_monthly_at_65,
        oas_monthly_at_65=oas_monthly_at_65,
        pension_monthly=pension_monthly,
        tfsa_room_remaining=tfsa_room_remaining,
        province=province,
    )
    params = ScenarioParams(
        name="Readiness Check",
        retirement_age=primary_age,
        longevity_age=longevity_age,
        target_annual_spending=annual_spending,
        inflation_rate_pct=2.5,
        portfolio_return_pct=5.0,
        cpp_start_age=cpp_start_age,
        oas_start_age=oas_start_age,
        sp_cpp_start_age=sp_cpp_start_age,
        sp_oas_start_age=sp_oas_start_age,
        province=province,
        base_tax_year=base_year,
    )

    try:
        rows    = project_scenario(primary, params, spouse=spouse)
        summary = scenario_summary(params, rows)
    except Exception as exc:
        logger.warning("readiness: projection failed: %s", exc)
        summary = {}

    # Household guaranteed annual income at CPP/OAS start ages
    cpp_annual  = cpp_annual_benefit(cpp_monthly_at_65, cpp_start_age)
    oas_annual  = oas_annual_benefit(oas_monthly_at_65, oas_start_age)
    pension_ann = pension_monthly * 12
    guaranteed  = cpp_annual + oas_annual + pension_ann

    if spouse:
        sp_cpp_age = sp_cpp_start_age if sp_cpp_start_age > 0 else cpp_start_age
        sp_oas_age = sp_oas_start_age if sp_oas_start_age > 0 else oas_start_age
        guaranteed += cpp_annual_benefit(spouse.cpp_monthly_at_65, sp_cpp_age)
        guaranteed += oas_annual_benefit(spouse.oas_monthly_at_65, sp_oas_age)
        guaranteed += spouse.pension_monthly * 12

    # Household totals for TFSA and liquidity components
    hh_tfsa_balance  = tfsa_balance  + (spouse.tfsa_balance            if spouse else 0.0)
    hh_tfsa_room     = tfsa_room_remaining + (spouse.tfsa_room_remaining if spouse else 0.0)
    hh_non_reg       = non_reg_balance + (spouse.non_registered_balance  if spouse else 0.0)
    hh_cumul_room    = cumulative_tfsa_room * (2 if spouse else 1)
    hh_rrsp          = rrsp_rrif_balance + (spouse.rrsp_rrif_balance     if spouse else 0.0)

    # Score components
    l_pts, l_detail = _longevity_score(summary, longevity_age, primary_age)
    c_pts, c_detail = _income_coverage_score(guaranteed, annual_spending)
    m_pts, m_detail = _mc_score(mc_prob_success)
    t_pts, t_detail = _tfsa_score(hh_tfsa_balance, hh_tfsa_room, hh_cumul_room)
    q_pts, q_detail = _liquidity_score(hh_non_reg, annual_spending)

    total = round(l_pts + c_pts + m_pts + t_pts + q_pts, 1)

    return {
        "score":  total,
        "label":  score_label(total),
        "components": [
            {"name": "Portfolio Longevity",    "weight": _LONGEVITY_WEIGHT,  "score": l_pts, "detail": l_detail},
            {"name": "Income Coverage",        "weight": _COVERAGE_WEIGHT,   "score": c_pts, "detail": c_detail},
            {"name": "Monte Carlo Confidence", "weight": _MC_WEIGHT,         "score": m_pts, "detail": m_detail},
            {"name": "TFSA Utilization",       "weight": _TFSA_WEIGHT,       "score": t_pts, "detail": t_detail},
            {"name": "Liquidity Buffer",       "weight": _LIQUIDITY_WEIGHT,  "score": q_pts, "detail": q_detail},
        ],
        "total_portfolio": round(hh_rrsp + hh_tfsa_balance + hh_non_reg, 2),
        "guaranteed_annual": round(guaranteed, 2),
        "disclaimer": (
            "Readiness score is a simplified planning indicator, not investment advice. "
            "Consult a financial planner for a comprehensive retirement assessment."
        ),
    }
