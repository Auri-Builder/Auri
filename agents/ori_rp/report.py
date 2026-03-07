"""
agents/ori_rp/report.py
-------------------------
One-page retirement plan summary report generator — Phase 3.

Produces a structured Markdown report suitable for:
  - On-screen display in a Streamlit expander
  - Download as a .md file (via st.download_button)
  - Future PDF export via weasyprint or reportlab (Phase 3+)

Every generated report includes the disclaimer as the first and last section,
per the architecture spec.

Annual review checklist
-----------------------
A separate function generates the annual review checklist covering:
  - TFSA room check
  - RRSP deadline reminder (March 1)
  - RRIF conversion upcoming (age 71 threshold)
  - RRIF minimum withdrawal due
  - OAS clawback exposure
  - CPP/OAS start decision pending

The checklist is embedded in the full report and also available standalone.
"""

from __future__ import annotations

from datetime import datetime, date

DISCLAIMER = (
    "**DISCLAIMER:** These projections are estimates only. Tax calculations use "
    "simplified marginal brackets and do not account for all deductions, credits, "
    "or personal circumstances. Consult your tax advisor, financial planner, and "
    "investment professional before acting on any projection in this tool. "
    "CPP and OAS benefit calculations are illustrative — use your My Service Canada "
    "statement for accurate figures."
)


def _fmt(v: float | None, prefix: str = "$") -> str:
    if v is None:
        return "—"
    return f"{prefix}{v:,.0f}" if prefix == "$" else f"{v:.1f}{prefix}"


def _pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}%"


# ---------------------------------------------------------------------------
# Annual review checklist
# ---------------------------------------------------------------------------

def annual_review_checklist(
    primary_age:         int,
    rrsp_rrif_balance:   float,
    tfsa_room_remaining: float,
    cpp_start_age:       int,
    oas_start_age:       int,
    cpp_started:         bool,
    oas_started:         bool,
    oas_clawback_risk:   bool,
    province:            str,
    year:                int,
) -> str:
    """
    Generate the annual review checklist as Markdown.

    Parameters
    ----------
    primary_age          : Current age of the primary investor.
    rrsp_rrif_balance    : Current RRSP/RRIF balance.
    tfsa_room_remaining  : TFSA contribution room available.
    cpp_start_age        : Planned CPP start age.
    oas_start_age        : Planned OAS start age.
    cpp_started          : True if CPP income has already begun.
    oas_started          : True if OAS income has already begun.
    oas_clawback_risk    : True if any scenario triggered OAS clawback.
    province             : Two-letter province code.
    year                 : Current calendar year.
    """
    today = date.today()
    lines = [
        f"## Annual Review Checklist — {year}",
        f"*Generated {today.isoformat()} · Province: {province}*",
        "",
        DISCLAIMER,
        "",
        "---",
        "",
    ]

    items = []

    # TFSA room
    if tfsa_room_remaining > 0:
        items.append(
            f"- [ ] **TFSA:** ${tfsa_room_remaining:,.0f} contribution room available. "
            "Consider topping up before year-end."
        )
    else:
        items.append("- [x] **TFSA:** Room fully used (verify after filing taxes).")

    # RRSP deadline
    if primary_age < 71:
        items.append(
            f"- [ ] **RRSP deadline:** Contributions for {year} tax year are due **March 1, {year + 1}**. "
            "Confirm your deduction limit on your CRA My Account notice of assessment."
        )
    else:
        items.append(
            "- [x] **RRSP → RRIF:** Your RRSP must convert to RRIF by Dec 31 of the year you turn 71. "
            "Confirm with your financial institution."
        )

    # RRIF minimum
    if primary_age >= 72 and rrsp_rrif_balance > 0:
        from agents.ori_rp.tax import rrif_minimum_withdrawal
        min_wd = rrif_minimum_withdrawal(rrsp_rrif_balance, primary_age)
        items.append(
            f"- [ ] **RRIF minimum withdrawal:** ~${min_wd:,.0f} must be withdrawn this year "
            f"(based on current balance and age {primary_age}). "
            "Ensure this has been processed before Dec 31."
        )
    elif 67 <= primary_age <= 71:
        items.append(
            f"- [ ] **RRIF conversion:** You will reach age 71 in {71 - primary_age + primary_age} "
            f"(in {71 - primary_age} year(s)). Plan RRIF conversion with your institution before then. "
            "Consider RRSP meltdown strategy to reduce future forced minimums."
        )

    # CPP
    if not cpp_started and primary_age >= 60:
        items.append(
            f"- [ ] **CPP start decision:** You planned to start CPP at age {cpp_start_age}. "
            "Review with your advisor — deferring to 70 increases benefit by 42% vs taking at 60."
        )
    elif cpp_started:
        items.append("- [x] **CPP:** Payments in progress. Verify amount on your Service Canada account.")

    # OAS
    if not oas_started and primary_age >= 64:
        items.append(
            f"- [ ] **OAS start decision:** You planned to start OAS at age {oas_start_age}. "
            "Apply 6 months before you want payments to begin (Service Canada processing time)."
        )
    elif oas_started:
        items.append("- [x] **OAS:** Payments in progress. Verify amount on your Service Canada account.")

    # OAS clawback
    if oas_clawback_risk:
        items.append(
            "- [ ] **OAS clawback risk:** One or more scenarios project net income above the "
            "clawback threshold (~$93,454 in 2026). Consider: TFSA withdrawals instead of RRIF, "
            "pension income splitting with spouse, or charitable giving to reduce net income."
        )

    # Pension income splitting (generic reminder)
    if primary_age >= 65:
        items.append(
            "- [ ] **Pension income splitting:** Eligible pension income (RRIF, annuity, DB pension) "
            "can be split with a spouse on your tax return. Review with your tax preparer."
        )

    lines += items
    lines += [
        "",
        "---",
        "",
        DISCLAIMER,
        "",
        f"*End of checklist — {today.isoformat()}*",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# One-page plan summary
# ---------------------------------------------------------------------------

def one_page_summary(
    scenario_name:  str,
    params_dict:    dict,
    summary:        dict,
    rows:           list,         # list[YearResult]
    primary_age:    int,
    province:       str,
    mc_result:      dict | None = None,
    year:           int | None = None,
) -> str:
    """
    Generate a one-page Markdown summary of a retirement scenario.

    Parameters
    ----------
    scenario_name : Name of the scenario (e.g. "Base Case").
    params_dict   : ScenarioParams fields as a dict (from scenario_to_dict["parameters"]).
    summary       : Output of scenario_summary().
    rows          : Output of project_scenario() (for 5-year withdrawal plan).
    primary_age   : Current age of primary investor.
    province      : Two-letter province code.
    mc_result     : Optional Monte Carlo results dict (from run_monte_carlo()).
    year          : Report year (defaults to current year).
    """
    today    = date.today()
    rep_year = year or today.year

    lines = [
        DISCLAIMER,
        "",
        "---",
        "",
        f"# Retirement Plan Summary — {scenario_name}",
        f"*{today.strftime('%B %d, %Y')} · Province: {province}*",
        "",
        "---",
        "",
        "## Scenario Parameters",
        "",
        f"| Parameter | Value |",
        f"|-----------|-------|",
        f"| Annual Spending Target | {_fmt(params_dict.get('target_annual_spending'))} (today's $) |",
        f"| Inflation Rate | {_pct(params_dict.get('inflation_rate_pct'))} |",
        f"| Portfolio Return (net) | {_pct(params_dict.get('portfolio_return_pct'))} |",
        f"| CPP Start Age | {params_dict.get('cpp_start_age', '—')} |",
        f"| OAS Start Age | {params_dict.get('oas_start_age', '—')} |",
        f"| Planning Horizon | Age {params_dict.get('longevity_age', 95)} |",
        "",
        "---",
        "",
        "## Portfolio Longevity",
        "",
    ]

    dep_age = summary.get("depletion_age")
    if dep_age:
        lines += [
            f"**⚠ Portfolio depleted at age {dep_age}.** "
            f"Shortfall begins in {dep_age - primary_age} year(s).",
            "",
            "Recommended actions:",
            "- Reduce spending target",
            "- Consider part-time bridge income",
            "- Optimize CPP/OAS timing",
            "- Review withdrawal sequencing strategy",
        ]
    else:
        lines += [
            f"**✓ Portfolio projected to last through age {params_dict.get('longevity_age', 95)}.**",
            f"Final balance: {_fmt(summary.get('final_portfolio'))}",
        ]

    # Monte Carlo results
    if mc_result:
        lines += [
            "",
            "### Monte Carlo Confidence Bands",
            f"*{mc_result['n_sims']} simulations · {mc_result['asset_mix']} portfolio "
            f"(σ = {mc_result['sigma_used']:.0f}%)*",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Probability of Success (portfolio > 0 at {params_dict.get('longevity_age', 95)}) "
            f"| **{mc_result['prob_success']:.1f}%** |",
            f"| P10 Final Balance (pessimistic) | {_fmt(mc_result['p10'][-1] if mc_result['p10'] else None)} |",
            f"| P50 Final Balance (median) | {_fmt(mc_result['p50'][-1] if mc_result['p50'] else None)} |",
            f"| P90 Final Balance (optimistic) | {_fmt(mc_result['p90'][-1] if mc_result['p90'] else None)} |",
        ]

    lines += [
        "",
        "---",
        "",
        "## Key Financials",
        "",
        f"| Metric | Amount |",
        f"|--------|--------|",
        f"| Total Estimated Taxes (lifetime) | {_fmt(summary.get('total_taxes'))} |",
        f"| Total CPP + OAS (lifetime) | {_fmt(summary.get('total_cpp_oas'))} |",
        f"| Total Portfolio Withdrawals | {_fmt(summary.get('total_withdrawals'))} |",
        f"| Peak Portfolio Value | {_fmt(summary.get('peak_portfolio'))} |",
        f"| Years with Spending Shortfall | {summary.get('years_with_shortfall', 0)} |",
        "",
        "---",
        "",
        "## 5-Year Withdrawal Plan",
        "",
        "Annual figures in nominal dollars (inflation-adjusted from today).",
        "",
        "| Year | Age | RRSP/RRIF ($) | Non-Reg ($) | TFSA ($) | Portfolio ($) | Tax Est. ($) | Spending ($) |",
        "|------|-----|--------------|------------|---------|--------------|-------------|-------------|",
    ]

    for r in rows[:5]:
        from_rrif    = r.rrsp_rrif_balance    # these are start-of-year balances
        # Compute per-account withdrawals from balance changes — approximate using portfolio_withdrawal
        # (Phase 1/2 detailed breakdown would need YearResult to carry per-account withdrawal fields)
        lines.append(
            f"| {r.year} | {r.age_primary} "
            f"| {_fmt(r.rrsp_rrif_balance)} "
            f"| {_fmt(r.non_reg_balance)} "
            f"| {_fmt(r.tfsa_balance)} "
            f"| {_fmt(r.portfolio_withdrawal)} "
            f"| {_fmt(r.taxes_estimated)} "
            f"| {_fmt(r.spending_delivered)} |"
        )

    lines += [
        "",
        "---",
        "",
    ]

    # Large expenditures
    large_exp = params_dict.get("large_expenditures", [])
    if large_exp:
        lines += [
            "## Planned Large Expenditures",
            "",
            "| Year | Amount | Label |",
            "|------|--------|-------|",
        ]
        for e in large_exp:
            lines.append(
                f"| {e.get('year', '—')} | {_fmt(e.get('amount'))} | {e.get('label', '—')} |"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

    # Key risks
    risks = []
    if dep_age and dep_age < (primary_age + 25):
        risks.append(f"**Portfolio depletion:** Projected at age {dep_age} — within 25 years.")
    if summary.get("years_with_shortfall", 0) > 0:
        risks.append(f"**Spending shortfalls:** {summary['years_with_shortfall']} year(s) of underfunding projected.")
    if mc_result and mc_result.get("prob_success", 100) < 80:
        risks.append(
            f"**Monte Carlo success rate below 80%:** "
            f"Only {mc_result['prob_success']:.1f}% of simulations sustain spending to age "
            f"{params_dict.get('longevity_age', 95)}."
        )

    if risks:
        lines += [
            "## Key Risks",
            "",
        ]
        for r in risks:
            lines.append(f"- {r}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines += [
        "",
        DISCLAIMER,
        "",
        f"*End of report — generated {today.isoformat()}*",
    ]

    return "\n".join(lines)
