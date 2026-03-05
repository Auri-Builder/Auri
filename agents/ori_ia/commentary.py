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

# ── System instruction embedded at the top of every prompt ──────────────────
_SYSTEM_INSTRUCTION = """\
You are a portfolio analyst reviewing an aggregated investment portfolio summary.
This data was produced by a local analytics system. All figures are totals or
weighted averages — there are no individual account identifiers, transaction
records, or personally identifying information in this dataset.

Provide your response in two sections:

**Observations** (3–5 bullet points)
Factual observations about the portfolio — concentration risk, sector exposure,
P&L patterns, registered vs. non-registered balance. Reference specific numbers.

**Questions** (2–3 items)
Open-ended clarifying questions about the investor's apparent intentions or
risk posture. Do not presuppose what changes should be made.

Constraints:
- Do not recommend specific trades, securities, or portfolio adjustments.
- Do not reference account numbers, file names, or institution names.
- Format in Markdown.
"""


def _fmt(value, spec: str = ",.2f") -> str:
    """Format a numeric value or return 'N/A' for None."""
    if value is None:
        return "N/A"
    return format(value, spec)


def build_prompt(summary: dict, philosophy: str | None = None) -> str:
    """
    Construct the LLM prompt from whitelisted summary fields only.

    Args:
        summary:    Output of build_summary() / handle_portfolio_summary_v0().
                    Only whitelisted keys are read — all others are ignored.
        philosophy: Optional free-text investment philosophy from profile.yaml.
                    Included verbatim so the LLM can contextualise its analysis.

    Returns:
        A structured plain-text + Markdown prompt.
    """
    lines: list[str] = [_SYSTEM_INSTRUCTION, ""]

    if philosophy:
        lines += [
            "---",
            "## Investor's Investment Philosophy",
            "",
            philosophy.strip(),
            "",
        ]

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

    lines += [
        "---",
        "Please provide your **Observations** and **Questions** based on the data above.",
    ]

    return "\n".join(lines)


def generate_commentary(summary: dict, adapter: "LLMAdapter", philosophy: str | None = None) -> dict:
    """
    Generate portfolio commentary using the provided LLM adapter.

    Args:
        summary:    Output of build_summary() / handle_portfolio_summary_v0().
        adapter:    An LLMAdapter instance (local or cloud).
        philosophy: Optional free-text investment philosophy from profile.yaml.

    Returns:
        {
            "commentary":    str  — full LLM response text (Markdown),
            "prompt_length": int  — character count of prompt (diagnostic),
        }

    Raises:
        Exception: propagated from the adapter if the LLM call fails.
    """
    prompt = build_prompt(summary, philosophy=philosophy)
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
