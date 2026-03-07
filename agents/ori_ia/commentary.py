"""
ORI_IA Portfolio Commentary
============================
Builds a structured prompt from portfolio summary aggregates (strict whitelist)
and calls the configured LLM adapter to produce observations and clarifying
questions.

Governance
----------
  - Only whitelisted aggregate fields are included in the prompt.
  - Per-position sub-totals (registered / non_registered / unclassified),
    account_count, and reconciliation_delta are excluded — they reveal
    internal account structure at a granular level.
  - The LLM receives no account identifiers, file paths, or institution names.
  - The system instruction explicitly prohibits trade recommendations and
    references to identifying information.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.ori_ia.llm_adapter import LLMAdapter

logger = logging.getLogger(__name__)

# ── Strict whitelist: position fields sent to the LLM ───────────────────────
_POSITION_LLM_FIELDS = (
    "symbol",
    "security_name",
    "sector",
    "asset_class",
    "market_value",
    "weight_pct",
    "cost_basis",
    "unrealized_gain",
    "unrealized_gain_pct",
)

# ── Standard commentary system instruction ──────────────────────────────────
_SYSTEM_INSTRUCTION = """\
You are a portfolio analyst reviewing an aggregated investment portfolio summary
for a specific investor whose profile is provided below.
This data was produced by a local analytics system. All figures are totals or
weighted averages — there are no individual account identifiers, transaction
records, or personally identifying information in this dataset.

Provide your response in two sections:

**Observations** (3–5 bullet points)
Factual observations about the portfolio relative to the investor's stated
profile — concentration risk, sector exposure relative to stated tolerances,
P&L patterns, income coverage of expenses, registered vs. non-registered
balance. Reference specific numbers and compare against stated constraints
where relevant.

**Questions** (2–3 items)
Open-ended clarifying questions grounded in the investor's profile and apparent
portfolio intentions. Do not presuppose what changes should be made.

Constraints:
- Do not recommend specific trades, securities, or portfolio adjustments.
- Do not reference account numbers, file names, or institution names.
- Format in Markdown.
"""

# ── Adversarial / challenge system instruction ───────────────────────────────
_CHALLENGE_INSTRUCTION = """\
You are a senior investment advisor playing the role of a rigorous, independent
second opinion on this portfolio. Your job is to surface risks, challenge
assumptions, and identify blind spots — not to validate existing decisions.
Be direct, specific, and evidence-based. Use the investor's profile to
calibrate your critique.

Provide your response in exactly four sections:

**Risks You May Not Be Seeing** (3 specific risks with supporting data)
Identify three portfolio risks the investor may be underestimating or overlooking.
For each risk, cite a specific number (weight %, dollar amount, or ratio) from
the data and explain why it matters given the investor's profile.

**Allocation Challenges** (2 recommendations with rationale)
Identify two changes you would make to the allocation and explain specifically why.
Reference the target weights, current weights, and investor goals. Be explicit
about trade-offs — what does the investor gain and give up with each change.

**Counter-opinion on the Investment Thesis**
State the strongest case AGAINST the investor's current positioning. What does
the investor's portfolio implicitly bet on, and where is that bet most vulnerable?
Reference macro context and the investor's stated constraints.

**One Position to Reconsider**
Identify one sector or position that warrants re-evaluation. Describe the
concern and what type of alternative exposure could address it without
abandoning the investor's strategy.

Constraints:
- Do not name specific securities to buy or sell (you only see aggregated data).
- Be constructively critical — not harsh. The goal is to improve the portfolio.
- Do not reference account numbers, file names, or institution names.
- Format in Markdown.
"""


def _fmt(value, spec: str = ",.2f") -> str:
    """Format a numeric value or return 'N/A' for None."""
    if value is None:
        return "N/A"
    return format(value, spec)


def _build_profile_section(profile: dict) -> list[str]:
    """
    Render a structured Investor Profile section from profile.yaml contents.
    Only safe, investor-supplied fields are included — no account identifiers.
    """
    lines: list[str] = ["---", "## Investor Profile", ""]

    derived = profile.get("derived", {})
    if derived.get("risk_score") is not None:
        lines.append(
            f"- **Risk Score:** {derived['risk_score']:.0f} / 100"
            f"  ({derived.get('risk_label', '—')})"
        )
    if derived.get("max_drawdown_tolerance_pct") is not None:
        lines.append(
            f"- **Max Drawdown Tolerance:** {derived['max_drawdown_tolerance_pct']:.0f}%"
        )

    goals = profile.get("goals", {})
    if goals.get("primary"):
        label = goals["primary"].replace("_", " ").title()
        lines.append(f"- **Primary Goal:** {label}")
    if goals.get("secondary"):
        label = goals["secondary"].replace("_", " ").title()
        lines.append(f"- **Secondary Goal:** {label}")

    horizon = profile.get("time_horizon", {})
    if horizon.get("years_to_significant_drawdown") is not None:
        lines.append(
            f"- **Years to Significant Drawdown:** {horizon['years_to_significant_drawdown']}"
        )
    if horizon.get("description"):
        lines += ["", f"*Horizon context:* {horizon['description'].strip()}", ""]

    constraints = profile.get("constraints", {})
    if constraints.get("max_single_position_pct") is not None:
        lines.append(
            f"- **Max Single Position:** {constraints['max_single_position_pct']:.0f}%"
        )
    if constraints.get("max_sector_pct") is not None:
        lines.append(
            f"- **Max Sector Weight:** {constraints['max_sector_pct']:.0f}%"
        )
    if constraints.get("min_cash_buffer_years") is not None:
        lines.append(
            f"- **Min Cash Buffer:** {constraints['min_cash_buffer_years']:.0f} years"
        )
    excluded = constraints.get("excluded_sectors") or []
    if excluded:
        lines.append(f"- **Excluded Sectors:** {', '.join(excluded)}")

    tax = profile.get("tax", {})
    if tax.get("registered_emphasis"):
        lines.append("- **Registered Account Emphasis:** Yes")
    if tax.get("notes"):
        lines += ["", f"*Tax notes:* {tax['notes'].strip()}", ""]

    retirement = profile.get("retirement", {})
    if retirement.get("annual_expenses_estimate") is not None:
        lines.append(
            f"- **Annual Expenses (Est.):** ${retirement['annual_expenses_estimate']:,.0f}"
        )
    if retirement.get("guaranteed_income_pct") is not None:
        pct = retirement["guaranteed_income_pct"]
        annual = retirement.get("annual_expenses_estimate")
        if annual:
            guaranteed = annual * pct / 100
            lines.append(
                f"- **Guaranteed Income:** {pct:.0f}% of expenses"
                f"  (~${guaranteed:,.0f}/year)"
            )

    philosophy = profile.get("philosophy") or ""
    if philosophy.strip():
        lines += [
            "",
            "**Investment Philosophy:**",
            "",
            philosophy.strip(),
        ]

    lines.append("")
    return lines


def build_prompt(
    summary: dict,
    profile: dict | None = None,
    income_summary: dict | None = None,
    mode: str = "standard",
) -> str:
    """
    Construct the LLM prompt from whitelisted summary fields only.

    Args:
        summary:        Output of build_summary() / handle_portfolio_summary_v0().
                        Only whitelisted keys are read — all others are ignored.
        profile:        Optional full profile dict from profile.yaml.
                        A structured "Investor Profile" section is injected so the
                        LLM can contextualise observations against stated goals,
                        constraints, and retirement context.
        income_summary: Optional output of compute_income_summary() from the
                        prices handler. Adds an Income Coverage section so the
                        LLM can assess dividend income against stated expenses.

    Returns:
        A structured plain-text + Markdown prompt.
    """
    instruction = _CHALLENGE_INSTRUCTION if mode == "challenge" else _SYSTEM_INSTRUCTION
    lines: list[str] = [instruction, ""]

    if profile:
        lines += _build_profile_section(profile)

    lines += [
        "---",
        "## Portfolio Data",
        "",
    ]

    # ── Portfolio-level metrics ──────────────────────────────────────────
    lines += [
        f"- **Total Market Value:** ${_fmt(summary.get('total_market_value'))}",
        f"- **Total Cost Basis:** ${_fmt(summary.get('total_cost_basis'))}",
        f"- **Unrealized Gain/Loss:** ${_fmt(summary.get('total_unrealized_gain'))} "
        f"({_fmt(summary.get('total_unrealized_gain_pct'), '.2f')}%)",
        f"- **Positions:** {summary.get('position_count', 0)}",
        f"- **Unique Symbols:** {summary.get('unique_symbols', 0)}",
        "",
    ]

    # ── Account type split ───────────────────────────────────────────────
    split = summary.get("account_type_split", {})
    if split:
        lines.append("**Account Type Split:**")
        for bucket, value in split.items():
            lines.append(f"- {bucket.replace('_', ' ').title()}: ${_fmt(value)}")
        lines.append("")

    # ── Sector weights ───────────────────────────────────────────────────
    sectors = summary.get("sector_weights_pct", {})
    if sectors:
        lines.append("**Sector Weights:**")
        for sector, pct in sectors.items():
            lines.append(f"- {sector}: {pct:.1f}%")
        lines.append("")

    # ── Concentration alerts ─────────────────────────────────────────────
    flags = summary.get("concentration_flags", [])
    threshold = summary.get("concentration_threshold_pct", 10.0)
    if flags:
        lines.append(f"**Concentration Alerts (>{threshold:.0f}%):**")
        for flag in flags:
            lines.append(f"- {flag['symbol']}: {flag['weight_pct']:.1f}%")
        lines.append("")

    # ── Per-symbol positions (strict whitelist) ──────────────────────────
    positions = summary.get("positions_summary", [])
    if positions:
        lines.append("**Positions (by market value, aggregated across all accounts):**")
        lines.append("")
        lines.append(
            f"| {'Symbol':<12} | {'Security':<28} | {'Sector':<20} | "
            f"{'Asset Class':<15} | {'Mkt Val ($)':>12} | {'Wt%':>6} | "
            f"{'Cost Basis ($)':>14} | {'Gain/Loss ($)':>13} | {'G/L%':>7} |"
        )
        lines.append(
            f"| {'-'*12} | {'-'*28} | {'-'*20} | {'-'*15} | "
            f"{'-'*12} | {'-'*6} | {'-'*14} | {'-'*13} | {'-'*7} |"
        )

        for p in positions:
            # Enforce whitelist — only access allowed keys
            sym  = (p.get("symbol") or "")[:12]
            name = (p.get("security_name") or "")[:28]
            sec  = (p.get("sector") or "")[:20]
            ac   = (p.get("asset_class") or "")[:15]
            mv   = p.get("market_value")
            wt   = p.get("weight_pct")
            cb   = p.get("cost_basis")
            ug   = p.get("unrealized_gain")
            ugp  = p.get("unrealized_gain_pct")

            lines.append(
                f"| {sym:<12} | {name:<28} | {sec:<20} | {ac:<15} | "
                f"{_fmt(mv):>12} | {_fmt(wt, '.1f'):>5}% | "
                f"{_fmt(cb):>14} | {_fmt(ug):>13} | {_fmt(ugp, '.1f'):>6}% |"
            )
        lines.append("")

    # ── Income coverage (live prices data, optional) ─────────────────────
    if income_summary:
        cad = income_summary.get("total_annual_income_cad")
        usd = income_summary.get("total_annual_income_usd")
        cad_pos = income_summary.get("income_positions_cad", 0)
        usd_pos = income_summary.get("income_positions_usd", 0)

        lines.append("**Estimated Annual Dividend Income (from live market data):**")
        if cad is not None:
            lines.append(f"- CAD income: ${_fmt(cad)}  ({cad_pos} positions)")
        if usd is not None:
            lines.append(f"- USD income: ${_fmt(usd)}  ({usd_pos} positions)")

        # Compute coverage against profile retirement data if available
        retirement = (profile or {}).get("retirement", {})
        annual_expenses = retirement.get("annual_expenses_estimate")
        guaranteed_pct  = retirement.get("guaranteed_income_pct")
        if annual_expenses and guaranteed_pct is not None and cad is not None:
            guaranteed = annual_expenses * guaranteed_pct / 100
            funding_gap = annual_expenses - guaranteed
            coverage_pct = cad / funding_gap * 100 if funding_gap > 0 else 0.0
            lines += [
                f"- Annual expenses: ${_fmt(annual_expenses)}",
                f"- Guaranteed income: ${_fmt(guaranteed)}/year",
                f"- Funding gap (expenses − guaranteed): ${_fmt(funding_gap)}",
                f"- CAD dividend coverage of gap: {coverage_pct:.1f}%",
            ]
        lines.append("")

    if mode == "challenge":
        lines += [
            "---",
            "Please provide your **Risks You May Not Be Seeing**, **Allocation Challenges**, "
            "**Counter-opinion on the Investment Thesis**, and **One Position to Reconsider** "
            "based on the data above.",
        ]
    else:
        lines += [
            "---",
            "Please provide your **Observations** and **Questions** based on the data above.",
        ]

    return "\n".join(lines)


def generate_commentary(
    summary: dict,
    adapter: "LLMAdapter",
    profile: dict | None = None,
    income_summary: dict | None = None,
    mode: str = "standard",
) -> dict:
    """
    Generate portfolio commentary using the provided LLM adapter.

    Args:
        summary:        Output of build_summary() / handle_portfolio_summary_v0().
        adapter:        An LLMAdapter instance (local or cloud).
        profile:        Optional full profile dict from profile.yaml.
        income_summary: Optional output of compute_income_summary() from the
                        prices handler. When present, dividend income and
                        expense coverage are included in the prompt.

    Returns:
        {
            "commentary":    str  — full LLM response text (Markdown),
            "prompt_length": int  — character count of prompt (diagnostic),
        }

    Raises:
        Exception: propagated from the adapter if the LLM call fails.
    """
    prompt = build_prompt(summary, profile=profile, income_summary=income_summary, mode=mode)
    logger.info(
        "Sending commentary prompt (%d chars) to %s",
        len(prompt),
        adapter.provider_label,
    )

    response = adapter.generate(prompt)
    logger.info("Commentary received (%d chars)", len(response))

    return {
        "commentary":    response,
        "prompt_length": len(prompt),
    }
