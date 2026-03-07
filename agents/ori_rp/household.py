"""
agents/ori_rp/household.py
----------------------------
Household-level tax analysis for the ORI Retirement Planner — Phase 4.

Functions
---------
1. Pension income splitting
   CRA allows up to 50% of eligible pension income to be allocated to a spouse.
   Eligible income: RRIF withdrawals, annuity payments, DB pension payments (age 65+).
   CPP and OAS are NOT eligible (they are split via the CPP sharing application,
   which is a separate Service Canada election).

   The planner models the full 50% split and computes:
   - Combined household tax without splitting
   - Combined household tax with splitting (at the chosen %)
   - Tax savings from splitting

2. RRSP spousal contributions
   Contributions to a spousal RRSP come from the contributor's deduction room
   but withdrawals are taxed in the spouse's hands (after 3-year attribution rule).
   The model computes the future tax saving when the lower-income spouse withdraws.

3. Combined household projection
   Merges primary and spouse cashflow rows into household-level totals for
   reporting (combined income, combined tax, combined spending delivered).

Disclaimer: These are simplified estimates. Income splitting eligibility depends
on personal circumstances. Consult your tax advisor before electing pension
income splitting on your T1.
"""

from __future__ import annotations

import logging

from agents.ori_rp.tax import estimate_tax

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "Income splitting calculations are estimates only. Eligibility depends on "
    "personal circumstances. Consult your tax advisor before electing pension "
    "income splitting on your T1 return."
)


# ---------------------------------------------------------------------------
# Pension income splitting
# ---------------------------------------------------------------------------

def compute_pension_split(
    primary_eligible_pension: float,   # RRIF + annuity + DB pension (age 65+ only for RRIF)
    primary_other_income:     float,   # CPP + OAS + part-time + non-reg (not splittable)
    spouse_income:            float,   # spouse total income (all sources, before split)
    split_pct:                float,   # 0–50%; CRA max is 50%
    province:                 str = "ON",
    year:                     int = 2026,
) -> dict:
    """
    Model pension income splitting between primary investor and spouse.

    CRA allows eligible pension income to be allocated to a lower-income spouse
    to reduce combined household taxes. The optimal split % depends on both
    spouses' marginal rates — this function lets you see the benefit at any
    split from 0% to 50%.

    Parameters
    ----------
    primary_eligible_pension : Eligible income that can be split (RRIF ≥65, DB pension, annuity).
    primary_other_income     : Non-splittable income (CPP, OAS, part-time, non-reg gains).
    spouse_income            : Spouse's total income before receiving any split amount.
    split_pct                : Fraction of eligible pension to allocate to spouse (0–50).
    province                 : Province for tax brackets.
    year                     : Tax year.

    Returns
    -------
    dict:
        split_amount           : float   dollars moved to spouse
        primary_taxable_before : float
        primary_taxable_after  : float
        spouse_taxable_before  : float
        spouse_taxable_after   : float
        primary_tax_before     : float
        primary_tax_after      : float
        spouse_tax_before      : float
        spouse_tax_after       : float
        combined_tax_before    : float
        combined_tax_after     : float
        tax_savings            : float
        optimal_split_hint     : str     suggested direction to optimize further
        disclaimer             : str
    """
    split_pct = min(max(0.0, split_pct), 50.0)
    split_amount = round(primary_eligible_pension * split_pct / 100.0, 2)

    primary_before = primary_eligible_pension + primary_other_income
    primary_after  = primary_before - split_amount
    spouse_before  = spouse_income
    spouse_after   = spouse_income + split_amount

    tx_pb = estimate_tax(primary_before, province, year)
    tx_pa = estimate_tax(primary_after,  province, year)
    tx_sb = estimate_tax(spouse_before,  province, year)
    tx_sa = estimate_tax(spouse_after,   province, year)

    combined_before = tx_pb["total_tax"] + tx_sb["total_tax"]
    combined_after  = tx_pa["total_tax"] + tx_sa["total_tax"]
    savings         = round(combined_before - combined_after, 2)

    # Hint: if primary marginal > spouse marginal after split, increase split %
    if tx_pa["marginal_rate_pct"] > tx_sa["marginal_rate_pct"] and split_pct < 50:
        hint = f"Primary marginal ({tx_pa['marginal_rate_pct']:.1f}%) > spouse marginal ({tx_sa['marginal_rate_pct']:.1f}%). Increasing split % may reduce taxes further."
    elif tx_sa["marginal_rate_pct"] > tx_pa["marginal_rate_pct"]:
        hint = f"Spouse marginal ({tx_sa['marginal_rate_pct']:.1f}%) > primary marginal ({tx_pa['marginal_rate_pct']:.1f}%). Reduce split % — you've gone too far."
    else:
        hint = "Marginal rates are balanced. This split % is near-optimal."

    return {
        "split_amount":           split_amount,
        "primary_taxable_before": round(primary_before, 2),
        "primary_taxable_after":  round(primary_after,  2),
        "spouse_taxable_before":  round(spouse_before,  2),
        "spouse_taxable_after":   round(spouse_after,   2),
        "primary_tax_before":     tx_pb["total_tax"],
        "primary_tax_after":      tx_pa["total_tax"],
        "spouse_tax_before":      tx_sb["total_tax"],
        "spouse_tax_after":       tx_sa["total_tax"],
        "combined_tax_before":    round(combined_before, 2),
        "combined_tax_after":     round(combined_after,  2),
        "tax_savings":            savings,
        "optimal_split_hint":     hint,
        "disclaimer":             DISCLAIMER,
    }


def find_optimal_split(
    primary_eligible_pension: float,
    primary_other_income:     float,
    spouse_income:            float,
    province:                 str = "ON",
    year:                     int = 2026,
    step:                     float = 5.0,
) -> dict:
    """
    Search 0%–50% in steps to find the split percentage that minimizes combined tax.

    Returns the same shape as compute_pension_split() for the optimal split,
    plus 'optimal_split_pct' and a comparison table.
    """
    best_savings = -1.0
    best_pct     = 0.0
    table        = []

    pct = 0.0
    while pct <= 50.0 + 0.001:
        result = compute_pension_split(
            primary_eligible_pension, primary_other_income, spouse_income,
            split_pct=pct, province=province, year=year,
        )
        table.append({"split_pct": round(pct, 1), "tax_savings": result["tax_savings"]})
        if result["tax_savings"] > best_savings:
            best_savings = result["tax_savings"]
            best_pct     = pct
        pct += step

    best = compute_pension_split(
        primary_eligible_pension, primary_other_income, spouse_income,
        split_pct=best_pct, province=province, year=year,
    )
    best["optimal_split_pct"] = best_pct
    best["split_table"]       = table
    return best


# ---------------------------------------------------------------------------
# RRSP spousal contribution tax benefit
# ---------------------------------------------------------------------------

def spousal_rrsp_tax_benefit(
    contributor_marginal_rate_pct: float,   # primary's marginal rate (% when contributing)
    withdrawer_marginal_rate_pct:  float,   # spouse's marginal rate (% when withdrawing)
    contribution_amount:           float,   # annual RRSP contribution amount
    years_to_withdrawal:           int,
    portfolio_return_pct:          float = 5.0,
) -> dict:
    """
    Estimate the tax benefit of making RRSP contributions to a spousal plan
    instead of own RRSP — the contributor gets the deduction at their higher
    rate; the spouse withdraws at their lower rate.

    This is a simplified model: it does not account for attribution rules
    (the 3-year rule means contributions made in the last 3 years are attributed
    back if withdrawn — ensure contributions predate withdrawal by 3 calendar years).

    Returns
    -------
    dict:
        future_value           : float   RRSP value at withdrawal (compounded)
        tax_at_contributor_rate: float   tax if withdrawn at contributor's rate
        tax_at_withdrawer_rate : float   tax at spouse's lower rate
        tax_saving             : float   difference
        effective_saving_pct   : float   saving as % of future value
        attribution_warning    : str     reminder about 3-year rule
    """
    # Compound contribution_amount for years_to_withdrawal at portfolio_return_pct
    fv = contribution_amount * ((1 + portfolio_return_pct / 100) ** years_to_withdrawal - 1) / (portfolio_return_pct / 100)

    tax_contributor = round(fv * contributor_marginal_rate_pct / 100, 2)
    tax_withdrawer  = round(fv * withdrawer_marginal_rate_pct  / 100, 2)
    saving          = round(tax_contributor - tax_withdrawer, 2)
    saving_pct      = round(saving / fv * 100, 2) if fv > 0 else 0.0

    return {
        "future_value":            round(fv, 2),
        "tax_at_contributor_rate": tax_contributor,
        "tax_at_withdrawer_rate":  tax_withdrawer,
        "tax_saving":              saving,
        "effective_saving_pct":    saving_pct,
        "attribution_warning": (
            "3-year attribution rule: spousal RRSP withdrawals in the year of "
            "contribution or the 2 calendar years following are attributed back "
            "to the contributor and taxed at their rate. Ensure contributions "
            "predate withdrawals by at least 3 full calendar years."
        ),
    }


# ---------------------------------------------------------------------------
# Household cashflow merge
# ---------------------------------------------------------------------------

def merge_household_rows(primary_rows: list, spouse_rows: list | None) -> list[dict]:
    """
    Merge primary and spouse YearResult lists into combined household annual totals.

    Primary rows drive the year sequence. Spouse rows are matched by index.
    Returns a list of dicts (not YearResult) for easy table rendering.
    """
    merged = []
    for i, pr in enumerate(primary_rows):
        sr = spouse_rows[i] if (spouse_rows and i < len(spouse_rows)) else None

        sp_cpp     = sr.cpp_income         if sr else 0.0
        sp_oas     = sr.oas_income         if sr else 0.0
        sp_pension = sr.pension_income     if sr else 0.0
        sp_wd      = sr.portfolio_withdrawal if sr else 0.0
        sp_tax     = sr.taxes_estimated    if sr else 0.0

        combined_income  = (pr.cpp_income + pr.oas_income + pr.pension_income + pr.part_time_income
                           + sp_cpp + sp_oas + sp_pension)
        combined_wd      = pr.portfolio_withdrawal + sp_wd
        combined_tax     = pr.taxes_estimated + sp_tax
        combined_spend   = pr.spending_delivered
        combined_pv      = pr.portfolio_value

        merged.append({
            "year":              pr.year,
            "age_primary":       pr.age_primary,
            "age_spouse":        pr.age_spouse,
            "combined_govt_income": round(combined_income, 2),
            "combined_withdrawal":  round(combined_wd,     2),
            "combined_tax":         round(combined_tax,    2),
            "spending_delivered":   round(combined_spend,  2),
            "portfolio_value":      round(combined_pv,     2),
        })

    return merged
