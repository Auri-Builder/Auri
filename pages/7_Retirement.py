"""
pages/7_Retirement.py
----------------------
ORI Retirement Planner — Phase 1

Pillars covered here:
  1. Scenario comparison — Base Case, Conservative, Optimistic (3 hardcoded scenarios)
  2. "Will I run out?" chart + spending dial
  3. Income waterfall (CPP | OAS | Part-time | Portfolio withdrawal by year)
  4. Account balance projection (RRSP/RRIF, TFSA, Non-Reg)
  5. CPP/OAS timing comparison table

All personal data stays local (retirement_profile.yaml is gitignored).
No network calls — purely local computation.

DISCLAIMER: These projections are estimates only. Tax calculations use simplified
marginal brackets and do not account for all deductions, credits, or personal
circumstances. Consult your tax advisor, financial planner, and investment
professional before acting on any projection in this tool. CPP and OAS benefit
calculations are illustrative — use your My Service Canada statement for
accurate figures.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT   = Path(__file__).parent.parent
PROFILE_PATH   = PROJECT_ROOT / "data" / "retirement" / "retirement_profile.yaml"
SCENARIOS_DIR  = PROJECT_ROOT / "data" / "retirement" / "scenarios"
REFS_DIR       = PROJECT_ROOT / "refs" / "retirement"

_DISCLAIMER = (
    "> **These projections are estimates only.** Tax calculations use simplified "
    "marginal brackets and do not account for all deductions, credits, or personal "
    "circumstances. Consult your tax advisor, financial planner, and investment "
    "professional before acting on any projection in this tool. CPP and OAS benefit "
    "calculations are illustrative — use your My Service Canada statement for "
    "accurate figures."
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Retirement Planner · Auri",
    page_icon="🏦",
    layout="wide",
)
from core.ui import hide_sidebar_nav; hide_sidebar_nav()  # noqa: E402

# ── Imports (lazy — keep startup fast) ───────────────────────────────────────
try:
    import pandas as pd
    import plotly.graph_objects as go
    _PLOTLY = True
except ImportError:
    _PLOTLY = False

try:
    import yaml
    _YAML = True
except ImportError:
    _YAML = False


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_profile() -> dict | None:
    if not _YAML:
        st.error("PyYAML not installed. Run: pip install pyyaml")
        return None
    if not PROFILE_PATH.exists():
        return None
    with PROFILE_PATH.open() as f:
        return yaml.safe_load(f)


def _save_scenario(scenario_dict: dict, scenario_name: str) -> Path:
    """Save scenario JSON to data/retirement/scenarios/{name}_{date}.json."""
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-z0-9_]+", "_", scenario_name.lower()).strip("_")
    date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path      = SCENARIOS_DIR / f"{safe_name}_{date_str}.json"
    with path.open("w") as f:
        json.dump(scenario_dict, f, indent=2)
    return path


def _fmt_dollar(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:,.0f}"


def _fmt_pct(v: float | None, decimals: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v:.{decimals}f}%"


# ── Build PersonProfile from profile dict ────────────────────────────────────

def _person_from_dict(d: dict, province: str = "ON"):
    from agents.ori_rp.cashflow import PersonProfile
    return PersonProfile(
        current_age            = int(d.get("current_age",            65)),
        rrsp_rrif_balance      = float(d.get("rrsp_rrif_balance",    0)),
        tfsa_balance           = float(d.get("tfsa_balance",         0)),
        non_registered_balance = float(d.get("non_registered_balance", 0)),
        cpp_monthly_at_65      = float(d.get("cpp_monthly_at_65",    0)),
        oas_monthly_at_65      = float(d.get("oas_monthly_at_65",    0)),
        pension_monthly        = float(d.get("pension_monthly",      0)),
        pension_start_age      = int(d.get("pension_start_age",     0)),
        tfsa_room_remaining    = float(d.get("tfsa_room_remaining",  0)),
        part_time_income       = float(d.get("part_time_income",     0)),
        part_time_until_age    = int(d.get("part_time_until_age",    0)),
        province               = d.get("province", province),
    )


# ── Run four scenarios (Phase 2 adds Tax-Optimized) ──────────────────────────

def _run_scenarios(
    primary, spouse, spending, province, base_year,
    retirement_age=None,
    cpp_start_age=65, oas_start_age=65,
    sp_cpp_start_age=0, sp_oas_start_age=0,
    auto_tfsa_routing=True,
    voluntary_tfsa_topup=0.0,
    slow_go_age=0, slow_go_reduction_pct=15.0,
    no_go_age=0,  no_go_reduction_pct=25.0,
):
    from agents.ori_rp.cashflow import ScenarioParams, project_scenario, scenario_to_dict, scenario_summary
    from agents.ori_rp.withdrawal import WithdrawalStrategy

    annual_target  = float(spending.get("annual_target", 80_000))
    inflation      = float(spending.get("inflation_rate_pct", 2.5))
    large_exp      = spending.get("large_expenditures", []) or []
    ret_age        = retirement_age if retirement_age is not None else primary.current_age

    # Optimistic/Tax-Optimized always defer to 70; Base/Conservative use the user's chosen ages
    opt_cpp = max(cpp_start_age, 70)
    opt_oas = max(oas_start_age, 70)
    opt_sp_cpp = max(sp_cpp_start_age, 70) if sp_cpp_start_age > 0 else 0
    opt_sp_oas = max(sp_oas_start_age, 70) if sp_oas_start_age > 0 else 0

    # Dynamic meltdown ceiling: distribute the RRSP evenly over the pre-CPP/OAS window.
    # Target per-person annual draw = avg_rrsp / years_to_cpp.
    #   • If that rate < spending gap: RRSP depletes naturally — no extra meltdown needed;
    #     ceiling = spending gap (acts like SIMPLE strategy, no forced extra draws).
    #   • If that rate > spending gap: RRSP would outlast the window — draw extra each year
    #     to spread it gently; ceiling = avg_rrsp / years (at most top of 2nd bracket).
    _meltdown_years  = max(1, opt_cpp - ret_age)
    _divisor         = 2 if spouse else 1
    _per_gap         = annual_target / _divisor
    _avg_rrsp        = (primary.rrsp_rrif_balance +
                        (spouse.rrsp_rrif_balance if spouse else 0.0)) / _divisor
    _dynamic_ceiling = min(max(_per_gap, _avg_rrsp / _meltdown_years), 114_750.0)

    _common = dict(
        longevity_age=95,
        target_annual_spending=annual_target,
        voluntary_tfsa_topup=voluntary_tfsa_topup,
        large_expenditures=large_exp,
        province=province,
        base_tax_year=base_year,
        sp_cpp_start_age=sp_cpp_start_age,
        sp_oas_start_age=sp_oas_start_age,
        auto_tfsa_routing=auto_tfsa_routing,
        slow_go_age=slow_go_age,
        slow_go_reduction_pct=slow_go_reduction_pct,
        no_go_age=no_go_age,
        no_go_reduction_pct=no_go_reduction_pct,
    )

    scenarios_raw = [
        ScenarioParams(
            name="Base Case",
            retirement_age=ret_age,
            inflation_rate_pct=inflation,
            portfolio_return_pct=5.0,
            cpp_start_age=cpp_start_age,
            oas_start_age=oas_start_age,
            withdrawal_strategy=WithdrawalStrategy.SIMPLE,
            **_common,
        ),
        ScenarioParams(
            name="Conservative",
            retirement_age=ret_age,
            inflation_rate_pct=3.0,
            portfolio_return_pct=3.5,
            cpp_start_age=cpp_start_age,
            oas_start_age=oas_start_age,
            withdrawal_strategy=WithdrawalStrategy.SIMPLE,
            **_common,
        ),
        ScenarioParams(
            name="Optimistic",
            retirement_age=ret_age,
            inflation_rate_pct=2.0,
            portfolio_return_pct=6.5,
            cpp_start_age=opt_cpp,
            oas_start_age=opt_oas,
            sp_cpp_start_age=opt_sp_cpp,
            sp_oas_start_age=opt_sp_oas,
            withdrawal_strategy=WithdrawalStrategy.SIMPLE,
            **{k: v for k, v in _common.items() if k not in ("sp_cpp_start_age", "sp_oas_start_age")},
        ),
        ScenarioParams(
            name="Tax-Optimized",
            retirement_age=ret_age,
            inflation_rate_pct=inflation,
            portfolio_return_pct=5.0,
            cpp_start_age=opt_cpp,        # defer CPP/OAS to use RRSP meltdown window
            oas_start_age=opt_oas,
            sp_cpp_start_age=opt_sp_cpp,
            sp_oas_start_age=opt_sp_oas,
            withdrawal_strategy=WithdrawalStrategy.RRSP_MELTDOWN,
            # Dynamic ceiling spreads the RRSP evenly over the pre-CPP/OAS window
            # at the lowest marginal rate. See _dynamic_ceiling calculation above.
            meltdown_income_ceiling=_dynamic_ceiling,
            **{k: v for k, v in _common.items() if k not in ("sp_cpp_start_age", "sp_oas_start_age")},
        ),
    ]

    results = []
    for sc in scenarios_raw:
        rows     = project_scenario(primary, sc, spouse=spouse)
        summary  = scenario_summary(sc, rows)
        sc_dict  = scenario_to_dict(sc, rows)
        results.append((sc, rows, summary, sc_dict))
    return results


# ── Phase 3: Monte Carlo chart ────────────────────────────────────────────────

def _mc_first_zero_age(values: list[float], ages: list[int]) -> int | None:
    """Return the age where a MC percentile band first reaches $0, or None if it never does."""
    for age, val in zip(ages, values):
        if val <= 0:
            return age
    return None


def _monte_carlo_chart(mc_result: dict, scenario_name: str):
    """Portfolio value with P10/P50/P90 confidence bands."""
    if not _PLOTLY:
        return
    import plotly.graph_objects as go

    ages = mc_result["ages"]
    p10  = mc_result["p10"]
    p50  = mc_result["p50"]
    p90  = mc_result["p90"]

    fig = go.Figure()

    # P90-P10 shaded band
    fig.add_trace(go.Scatter(
        name="P90 (Optimistic)",
        x=ages, y=p90,
        mode="lines",
        line=dict(color="#2563EB", width=1, dash="dot"),
        hovertemplate="<b>P90</b><br>Age %{x}<br>$%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        name="P10 (Pessimistic)",
        x=ages, y=p10,
        mode="lines",
        fill="tonexty",
        fillcolor="rgba(37,99,235,0.12)",
        line=dict(color="#2563EB", width=1, dash="dot"),
        hovertemplate="<b>P10</b><br>Age %{x}<br>$%{y:,.0f}<extra></extra>",
    ))
    # P50 median — solid
    fig.add_trace(go.Scatter(
        name="P50 (Median)",
        x=ages, y=p50,
        mode="lines",
        line=dict(color="#2563EB", width=3),
        hovertemplate="<b>P50 Median</b><br>Age %{x}<br>$%{y:,.0f}<extra></extra>",
    ))

    fig.add_hline(y=0, line_color="#374151", line_dash="dash", line_width=1)

    fig.update_layout(
        title=(
            f"Monte Carlo — {scenario_name} "
            f"({mc_result['n_sims']} simulations · "
            f"{mc_result['asset_mix']} σ={mc_result['sigma_used']:.0f}%)"
        ),
        xaxis_title="Age",
        yaxis_title="Portfolio Value ($)",
        yaxis_tickformat="$,.0f",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=420,
        margin=dict(l=0, r=0, t=60, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Charts ───────────────────────────────────────────────────────────────────

_SCENARIO_COLOURS = {
    "Base Case":    "#2563EB",   # blue
    "Conservative": "#DC2626",   # red
    "Optimistic":   "#16A34A",   # green
    "Tax-Optimized": "#9333EA",  # purple
}


def _portfolio_chart(scenario_runs):
    """'Will I run out?' — portfolio value over time for all scenarios."""
    if not _PLOTLY:
        st.info("Install plotly for charts: pip install plotly")
        return

    fig = go.Figure()
    for sc, rows, summary, _ in scenario_runs:
        colour = _SCENARIO_COLOURS.get(sc.name, "#6B7280")
        ages   = [r.age_primary for r in rows]
        vals   = [r.portfolio_value for r in rows]

        fig.add_trace(go.Scatter(
            x=ages,
            y=vals,
            mode="lines",
            name=sc.name,
            line=dict(color=colour, width=2.5),
            hovertemplate=(
                f"<b>{sc.name}</b><br>"
                "Age %{x}<br>"
                "Portfolio: $%{y:,.0f}<extra></extra>"
            ),
        ))

        # Mark depletion year
        dep_age = summary.get("depletion_age")
        if dep_age:
            fig.add_vline(
                x=dep_age,
                line=dict(color=colour, dash="dot", width=1.5),
                annotation_text=f"{sc.name}: depleted age {dep_age}",
                annotation_position="top right",
                annotation_font_color=colour,
            )

    fig.add_hline(y=0, line_color="#374151", line_dash="dash", line_width=1)
    fig.update_layout(
        hovermode="x unified",
        title="Portfolio Value Over Time — Will I Run Out?",
        xaxis_title="Age",
        yaxis_title="Portfolio Value ($)",
        yaxis_tickformat="$,.0f",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=420,
        margin=dict(l=0, r=0, t=60, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)


def _income_waterfall_chart(rows, scenario_name: str, sc=None):
    """Stacked bar: CPP | OAS | Pension | Part-time | Portfolio withdrawal per year."""
    if not _PLOTLY:
        return

    ages      = [r.age_primary              for r in rows]
    cpp       = [r.cpp_income              for r in rows]
    oas       = [r.oas_income              for r in rows]
    pension   = [r.pension_income          for r in rows]
    parttime  = [r.part_time_income        for r in rows]
    w_rrif    = [r.withdrawal_from_rrif    for r in rows]
    w_non_reg = [r.withdrawal_from_non_reg for r in rows]
    w_tfsa    = [r.withdrawal_from_tfsa    for r in rows]
    target    = [r.spending_target         for r in rows]

    fig = go.Figure()

    # ── Spending phase bands ───────────────────────────────────────────────
    if sc and ages:
        age_min, age_max = ages[0], ages[-1]
        slow_go = getattr(sc, "slow_go_age", 0)
        no_go   = getattr(sc, "no_go_age", 0)

        # Go-Go band (retirement start → slow-go or end)
        go_go_end = slow_go if slow_go > age_min else (no_go if no_go > age_min else age_max)
        if go_go_end > age_min:
            fig.add_vrect(x0=age_min, x1=go_go_end,
                          fillcolor="#DCFCE7", opacity=0.25, layer="below", line_width=0,
                          annotation_text="Go-Go", annotation_position="top left",
                          annotation_font_size=11, annotation_font_color="#15803D")

        # Slow-Go band
        if slow_go > age_min:
            slow_go_end = no_go if (no_go > slow_go) else age_max
            fig.add_vrect(x0=slow_go, x1=slow_go_end,
                          fillcolor="#FEF9C3", opacity=0.30, layer="below", line_width=0,
                          annotation_text="Slow-Go", annotation_position="top left",
                          annotation_font_size=11, annotation_font_color="#92400E")

        # No-Go band
        if no_go > age_min:
            fig.add_vrect(x0=no_go, x1=age_max,
                          fillcolor="#FEE2E2", opacity=0.25, layer="below", line_width=0,
                          annotation_text="No-Go", annotation_position="top left",
                          annotation_font_size=11, annotation_font_color="#991B1B")

    for label, data, colour in [
        ("CPP",            cpp,       "#2563EB"),
        ("OAS",            oas,       "#7C3AED"),
        ("Pension",        pension,   "#0891B2"),
        ("Part-time",      parttime,  "#059669"),
        ("RRSP/RRIF Draw", w_rrif,    "#D97706"),
        ("Non-Reg Draw",   w_non_reg, "#F59E0B"),
        ("TFSA Draw",      w_tfsa,    "#10B981"),
    ]:
        if any(v > 0 for v in data):
            fig.add_trace(go.Bar(
                name=label, x=ages, y=data,
                marker_color=colour,
                hovertemplate=f"<b>{label}</b><br>$%{{y:,.0f}}<extra></extra>",
            ))

    fig.add_trace(go.Scatter(
        name="Spending Target",
        x=ages,
        y=target,
        mode="lines",
        line=dict(color="#374151", dash="dot", width=2),
        hovertemplate="<b>Target</b><br>$%{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(
        barmode="stack",
        hovermode="x unified",
        title=f"Income Sources by Year — {scenario_name}",
        xaxis_title="Age",
        yaxis_title="Annual Income ($)",
        yaxis_tickformat="$,.0f",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=400,
        margin=dict(l=0, r=0, t=60, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)


def _account_balance_chart(rows, scenario_name: str, sc=None):
    """Stacked area: RRSP/RRIF, TFSA, Non-Reg balances over time."""
    if not _PLOTLY:
        return

    ages    = [r.age_primary       for r in rows]
    rrif    = [r.rrsp_rrif_balance for r in rows]
    tfsa    = [r.tfsa_balance      for r in rows]
    non_reg = [r.non_reg_balance   for r in rows]

    fig = go.Figure()
    for label, data, colour in [
        ("RRSP/RRIF",      rrif,    "#2563EB"),
        ("Non-Registered", non_reg, "#D97706"),
        ("TFSA",           tfsa,    "#16A34A"),
    ]:
        fig.add_trace(go.Scatter(
            name=label, x=ages, y=data,
            mode="lines",
            stackgroup="one",
            fillcolor=colour,
            line=dict(color=colour, width=1),
            hovertemplate=f"<b>{label}</b><br>$%{{y:,.0f}}<extra></extra>",
        ))

    # ── Milestone lines ────────────────────────────────────────────────────
    if sc and ages:
        age_min, age_max = ages[0], ages[-1]
        milestones = []
        if age_min <= 71 <= age_max:
            milestones.append((71, "#6B7280", "RRIF conversion"))
        cpp_age = getattr(sc, "cpp_start_age", 0)
        if cpp_age and age_min <= cpp_age <= age_max:
            milestones.append((cpp_age, "#2563EB", f"CPP starts ({cpp_age})"))
        oas_age = getattr(sc, "oas_start_age", 0)
        if oas_age and age_min <= oas_age <= age_max and oas_age != cpp_age:
            milestones.append((oas_age, "#7C3AED", f"OAS starts ({oas_age})"))
        for age, colour, label in milestones:
            fig.add_vline(x=age, line=dict(color=colour, dash="dash", width=1.5),
                          annotation_text=label, annotation_position="top right",
                          annotation_font_size=10, annotation_font_color=colour)

    fig.update_layout(
        hovermode="x unified",
        title=f"Account Balances by Type — {scenario_name}",
        xaxis_title="Age",
        yaxis_title="Balance ($)",
        yaxis_tickformat="$,.0f",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=380,
        margin=dict(l=0, r=0, t=60, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)


def _tax_timeline_chart(rows, scenario_name: str, sc=None):
    """Annual estimated tax burden over retirement."""
    if not _PLOTLY:
        return

    ages  = [r.age_primary     for r in rows]
    taxes = [r.taxes_estimated for r in rows]
    clbk  = [r.oas_clawback    for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        name="Income Tax",
        x=ages, y=taxes,
        mode="lines+markers",
        line=dict(color="#DC2626", width=2),
        hovertemplate="<b>Tax</b><br>Age %{x}<br>$%{y:,.0f}<extra></extra>",
    ))
    if any(v > 0 for v in clbk):
        fig.add_trace(go.Bar(
            name="OAS Clawback",
            x=ages, y=clbk,
            marker_color="#F59E0B",
            hovertemplate="<b>OAS Clawback</b><br>Age %{x}<br>$%{y:,.0f}<extra></extra>",
        ))

    # ── OAS clawback threshold line ────────────────────────────────────────
    # Threshold kicks in at ~$93,454 net income (2026); tax on excess = 15%
    # As a guide, show what $93k income would cost in tax — rough horizontal marker
    # More useful: show the CPP/OAS start age as a vertical so viewer can see
    # when tax jumps as government income begins.
    if sc and ages:
        age_min, age_max = ages[0], ages[-1]
        cpp_age = getattr(sc, "cpp_start_age", 0)
        oas_age = getattr(sc, "oas_start_age", 0)
        if cpp_age and age_min <= cpp_age <= age_max:
            fig.add_vline(x=cpp_age, line=dict(color="#2563EB", dash="dash", width=1.5),
                          annotation_text=f"CPP starts", annotation_position="top right",
                          annotation_font_size=10, annotation_font_color="#2563EB")
        if oas_age and age_min <= oas_age <= age_max and oas_age != cpp_age:
            fig.add_vline(x=oas_age, line=dict(color="#7C3AED", dash="dash", width=1.5),
                          annotation_text=f"OAS starts", annotation_position="top right",
                          annotation_font_size=10, annotation_font_color="#7C3AED")
        if age_min <= 71 <= age_max:
            fig.add_vline(x=71, line=dict(color="#6B7280", dash="dot", width=1.2),
                          annotation_text="RRIF mandatory min", annotation_position="top left",
                          annotation_font_size=10, annotation_font_color="#6B7280")

    fig.update_layout(
        hovermode="x unified",
        title=f"Estimated Tax Burden — {scenario_name}",
        xaxis_title="Age",
        yaxis_title="Taxes ($)",
        yaxis_tickformat="$,.0f",
        height=340,
        margin=dict(l=0, r=0, t=60, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── CPP/OAS timing table ─────────────────────────────────────────────────────

def _cpp_oas_timing_section(primary):
    from agents.ori_rp.cpp_oas import cpp_timing_comparison, oas_timing_comparison

    st.subheader("CPP & OAS Timing Comparison")
    st.caption(
        "Monthly and annual benefit amounts in today's dollars. "
        "Break-even is the age at which cumulative lifetime income from a later start date "
        "surpasses the earlier start (nominal, not discounted)."
    )

    col_cpp, col_oas = st.columns(2)

    with col_cpp:
        st.markdown("**CPP — Start Age Options (60–70)**")
        cpp_rows = cpp_timing_comparison(primary.cpp_monthly_at_65)
        if _PLOTLY:
            import pandas as pd
            df = pd.DataFrame(cpp_rows)
            df.columns = ["Start Age", "Monthly ($)", "Annual ($)", "vs Age 65 (%)", "Break-even vs 65"]
            df["Monthly ($)"]  = df["Monthly ($)"].map(lambda v: f"${v:,.2f}")
            df["Annual ($)"]   = df["Annual ($)"].map(lambda v: f"${v:,.0f}")
            df["vs Age 65 (%)"] = df["vs Age 65 (%)"].map(lambda v: f"{v:+.1f}%")
            df["Break-even vs 65"] = df["Break-even vs 65"].map(
                lambda v: f"Age {v}" if v else "—"
            )
            st.dataframe(df, use_container_width=True, hide_index=True)

    with col_oas:
        st.markdown("**OAS — Start Age Options (65–70)**")
        oas_rows = oas_timing_comparison(primary.oas_monthly_at_65)
        if _PLOTLY:
            import pandas as pd
            df = pd.DataFrame(oas_rows)
            df.columns = ["Start Age", "Monthly ($)", "Annual ($)", "vs Age 65 (%)", "Break-even vs 65"]
            df["Monthly ($)"]  = df["Monthly ($)"].map(lambda v: f"${v:,.2f}")
            df["Annual ($)"]   = df["Annual ($)"].map(lambda v: f"${v:,.0f}")
            df["vs Age 65 (%)"] = df["vs Age 65 (%)"].map(lambda v: f"{v:+.1f}%")
            df["Break-even vs 65"] = df["Break-even vs 65"].map(
                lambda v: f"Age {v}" if v else "—"
            )
            st.dataframe(df, use_container_width=True, hide_index=True)


# ── Phase 2: Tax efficiency panels ───────────────────────────────────────────

def _withdrawal_strategy_comparison(primary, spending, province, base_year):
    """
    Show a single-year comparison of the three withdrawal strategies
    so the investor can see the tax impact of sequencing choices.
    """
    from agents.ori_rp.withdrawal import compare_withdrawal_strategies
    from agents.ori_rp.cpp_oas import cpp_annual_benefit, oas_annual_benefit

    st.subheader("Withdrawal Strategy Comparison")
    st.caption(
        "How much tax would you pay in the first retirement year under each "
        "withdrawal sequencing strategy? All three fund the same spending — "
        "the difference is where the money comes from and how it's taxed."
    )

    # Estimate first-year guaranteed income at Base Case CPP/OAS start ages (65/65)
    inflation_factor = 1.0  # first year, no inflation adjustment needed
    cpp_annual = cpp_annual_benefit(primary.cpp_monthly_at_65, 65) * inflation_factor
    oas_annual = oas_annual_benefit(primary.oas_monthly_at_65, 65) * inflation_factor
    pension    = primary.pension_monthly * 12
    guaranteed = cpp_annual + oas_annual + pension

    annual_target = float(spending.get("annual_target", 80_000))
    income_gap    = max(0.0, annual_target - guaranteed)

    is_rrif = primary.current_age > 71

    rows = compare_withdrawal_strategies(
        spending_need=income_gap,
        rrif_balance=primary.rrsp_rrif_balance,
        non_reg_balance=primary.non_registered_balance,
        tfsa_balance=primary.tfsa_balance,
        other_taxable_income=guaranteed,
        age=primary.current_age,
        province=province,
        year=base_year,
        is_rrif=is_rrif,
    )

    import pandas as pd
    df = pd.DataFrame(rows)
    df["strategy"] = df["strategy"].map({
        "simple":        "Simple (RRIF first)",
        "bracket_fill":  "Bracket Fill",
        "rrsp_meltdown": "RRSP Meltdown",
    })
    df.columns = ["Strategy", "From RRIF ($)", "From Non-Reg ($)", "From TFSA ($)",
                  "Taxable Income ($)", "Est. Tax ($)", "Effective Rate (%)"]
    for col in ["From RRIF ($)", "From Non-Reg ($)", "From TFSA ($)",
                "Taxable Income ($)", "Est. Tax ($)"]:
        df[col] = df[col].map(lambda v: f"${v:,.0f}")
    df["Effective Rate (%)"] = df["Effective Rate (%)"].map(lambda v: f"{v:.1f}%")

    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(
        "Non-registered withdrawals use a 50% capital gains inclusion (simplified). "
        "TFSA withdrawals are tax-free and not included in taxable income. "
        "RRSP Meltdown accelerates RRIF withdrawals up to the top of the 1st federal bracket (~$57,375) "
        "to gently reduce the RRSP over your pre-CPP/OAS window at the lowest marginal rate, "
        "avoiding large forced withdrawals after RRIF conversion at age 71."
    )


def _oas_clawback_alerts(scenario_runs):
    """Show a warning if any scenario triggers OAS clawback years."""
    clawback_warnings = []
    for sc, rows, summary, _ in scenario_runs:
        clawback_years = [(r.age_primary, r.oas_clawback) for r in rows if r.oas_clawback > 0]
        if clawback_years:
            total_clawback = sum(v for _, v in clawback_years)
            clawback_warnings.append((sc.name, clawback_years, total_clawback))

    if not clawback_warnings:
        st.success("No OAS clawback triggered in any scenario.")
        return

    for sc_name, years, total in clawback_warnings:
        first_age, _ = years[0]
        st.warning(
            f"**{sc_name}:** OAS clawback triggered at age {first_age} "
            f"({len(years)} year{'s' if len(years) > 1 else ''}, "
            f"total ~{_fmt_dollar(total)} clawed back). "
            "Consider TFSA drawdown or income splitting to stay below the threshold.",
            icon="⚠️",
        )


def _tfsa_room_section(primary, base_year):
    """Display TFSA room status and re-contribution planning."""
    from agents.ori_rp.withdrawal import compute_tfsa_room

    st.subheader("TFSA Room Tracker")
    room = compute_tfsa_room(
        tfsa_room_remaining=primary.tfsa_room_remaining,
        current_year=base_year,
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Room Available Now", _fmt_dollar(room["room_now"]))
    c2.metric("Room Next Jan 1", _fmt_dollar(room["room_next_year"]),
              help="Includes this year's new limit + any withdrawals made this year (restored next Jan 1).")
    c3.metric("Annual New Room", _fmt_dollar(room["annual_limit"]),
              help=f"New TFSA contribution room added in {base_year}.")

    if room["over_contribution"]:
        st.error(
            "⚠ Over-contribution detected. CRA charges 1%/month on the excess amount. "
            "Withdraw the excess immediately to stop the penalty.",
        )
    else:
        st.caption(
            "TFSA withdrawals restore room on January 1 of the following year. "
            "The room shown above is from your profile — update `tfsa_room_remaining` "
            "each year after filing your taxes."
        )


# ── Tax Efficiency Insight panel ─────────────────────────────────────────────

def _tax_efficiency_panel(scenario_runs, province: str, base_year: int):
    """
    Show which federal bracket each person is in for the first retirement year,
    how much room they have to the next boundary, and the suggested annual
    RRSP/RRIF draw to fill the bracket (i.e. the RRSP meltdown target).
    """
    from agents.ori_rp.tax import estimate_tax

    st.subheader("Tax Efficiency Guide")
    st.caption(
        "Based on your Base Case projection. "
        "Drawing more from RRSP/RRIF up to a bracket ceiling ('meltdown') while rates are low "
        "shelters the money in TFSA and avoids larger forced withdrawals at 71+."
    )

    # Use first retirement year of Base Case (scenario_runs[0])
    _, base_rows, _, _ = scenario_runs[0]
    first_ret = next((r for r in base_rows if r.spending_target > 0), None)
    if first_ret is None:
        st.info("Run a projection with a retirement age to see tax efficiency insights.")
        return

    # Federal brackets 2026 (approximate)
    FED_BRACKETS = [
        (57_375,   0.15,  "1st bracket (15%) — up to $57,375"),
        (114_750,  0.205, "2nd bracket (20.5%) — up to $114,750"),
        (159_180,  0.26,  "3rd bracket (26%) — up to $159,180"),
        (220_000,  0.29,  "4th bracket (29%) — up to $220,000"),
        (float("inf"), 0.33, "5th bracket (33%) — above $220,000"),
    ]

    def bracket_info(taxable: float):
        for ceiling, rate, label in FED_BRACKETS:
            if taxable <= ceiling:
                room = max(0.0, ceiling - taxable)
                return label, rate, room, ceiling
        return FED_BRACKETS[-1][2], FED_BRACKETS[-1][1], 0.0, float("inf")

    # Estimate per-person taxable income in the first retirement year
    # We use total household RRIF draw split 50/50 as a proxy (actual split varies)
    total_rrif = first_ret.withdrawal_from_rrif
    total_cpp_oas = first_ret.cpp_income + first_ret.oas_income
    total_pension = first_ret.pension_income

    # Single-person taxable estimate (per-person = roughly half)
    p_taxable = (total_rrif + total_cpp_oas + total_pension) / 2

    p_label, p_rate, p_room, p_ceiling = bracket_info(p_taxable)

    cols = st.columns(3)
    cols[0].metric(
        "Est. Taxable Income (per person, yr 1)",
        _fmt_dollar(p_taxable),
        help="First retirement year: (RRIF draw + CPP + OAS + Pension) ÷ 2. Approximate.",
    )
    cols[1].metric(
        "Current Bracket",
        p_label.split(" — ")[0],
        help=p_label,
    )
    cols[2].metric(
        "Room to Bracket Ceiling",
        _fmt_dollar(p_room),
        help=f"You could draw up to {_fmt_dollar(p_room)} more per person from RRSP/RRIF "
             f"before crossing into the next bracket (ceiling: {_fmt_dollar(p_ceiling)}).",
    )

    if p_room > 500:
        st.info(
            f"**Meltdown opportunity:** Each person has ~{_fmt_dollar(p_room)} of room in "
            f"their current bracket. Drawing this extra amount from RRSP/RRIF each year "
            f"and sheltering it in TFSA accelerates tax-sheltered growth and reduces "
            f"future forced RRIF minimums. The **Tax-Optimized** scenario models this strategy.",
            icon="💡",
        )
    elif p_room < 100:
        st.warning(
            "You are near or at a bracket boundary. Additional RRSP/RRIF draws would be "
            "taxed at a higher marginal rate — consider drawing primarily from TFSA or "
            "non-registered to avoid crossing the bracket.",
            icon="⚠️",
        )
    else:
        st.success(
            "Your income is well-positioned within your current bracket. "
            "No urgent meltdown needed.",
        )


# ── Profile editor form ──────────────────────────────────────────────────────

def _profile_form() -> dict | None:
    """
    Render a Streamlit form to input or override retirement profile data.
    Returns a profile dict in the same shape as retirement_profile.yaml.
    """
    st.subheader("Retirement Profile")
    st.caption("Enter your current financial details. This data is used only for local computation and is never transmitted.")

    # ── Pull defaults from shared profile + portfolio CSV ─────────────────
    try:
        from core.shared_profile import load_shared_profile, get_account_balances  # noqa: PLC0415
        _sp      = load_shared_profile()
        _sp_p    = _sp.get("primary", {})
        _sp_s    = _sp.get("spouse")
        _acct    = get_account_balances()
        from agents.ori_ia.schema import REGISTERED_ACCOUNT_TYPES as _REG  # noqa: PLC0415
        _rrsp_bal    = float(_acct.get("RRSP", 0) or _acct.get("RRIF", 0))
        _tfsa_bal    = float(_acct.get("TFSA", 0))
        _non_reg_bal = float(sum(v for k, v in _acct.items() if k not in _REG))
        _age_def     = int(_sp_p.get("current_age", 55))
        _ret_def     = int(_sp_p.get("target_retirement_age", 65))
        _prov_def    = _sp_p.get("province")
        _has_sp_def  = _sp_s is not None
        _sp_age_def  = int((_sp_s or {}).get("current_age", 55))
        if _rrsp_bal or _tfsa_bal:
            st.info(
                f"Account balances pre-filled from portfolio CSV — "
                f"RRSP ${_rrsp_bal:,.0f} \u00b7 TFSA ${_tfsa_bal:,.0f}. "
                "Adjust if your balances have changed since the last upload."
            )
    except Exception:
        _age_def = 55; _ret_def = 65; _prov_def = None
        _rrsp_bal = 450_000.0; _tfsa_bal = 95_000.0; _non_reg_bal = 180_000.0
        _has_sp_def = False; _sp_age_def = 55


    # has_spouse OUTSIDE the form so toggling it immediately shows/hides spouse fields
    # without requiring a form submit first.
    has_spouse = st.checkbox(
        "Add spouse / common-law partner",
        value=_has_sp_def,
        key="rp_has_spouse",
    )

    _PROV_OPTIONS = ["ON", "BC", "AB", "QC", "MB", "SK", "NS", "NB", "PE", "NL"]

    with st.form("retirement_profile_form"):
        st.markdown("**Primary Person**")
        c1, c2, c3 = st.columns(3)
        age        = c1.number_input("Current Age",    min_value=_age_def, max_value=_age_def, value=_age_def, step=1)
        ret_age    = c2.number_input("Retirement Age", min_value=_ret_def, max_value=_ret_def, value=_ret_def, step=1)
        # Default to last-used province (persisted in session_state)
        _prov_default = _prov_def or st.session_state.get("rp_province", "ON")
        _prov_idx  = _PROV_OPTIONS.index(_prov_default) if _prov_default in _PROV_OPTIONS else 0
        province   = c3.selectbox("Province", _PROV_OPTIONS, index=_prov_idx)

        c4, c5, c6, c7 = st.columns(4)
        cpp_mo        = c4.number_input("CPP at 65 ($/mo)",         min_value=0.0, max_value=1400.0, value=1200.0, step=50.0)
        cpp_start     = c5.number_input("CPP Start Age",            min_value=60,  max_value=70,     value=65,     step=1,
                                        help="Age you plan to start CPP (60–70). Deferring past 65 increases benefit by 0.7%/month.")
        oas_mo        = c6.number_input("OAS at 65 ($/mo)",         min_value=0.0, max_value=800.0,  value=700.0,  step=10.0)
        oas_start     = c7.number_input("OAS Start Age",            min_value=65,  max_value=70,     value=65,     step=1,
                                        help="Age you plan to start OAS (65–70). Deferring past 65 increases benefit by 0.6%/month.")

        c8, c9, c10, c11 = st.columns(4)
        pension       = c8.number_input("DB Pension ($/mo)",        min_value=0.0, max_value=20000.0, value=0.0,   step=100.0)
        pension_start = c9.number_input("Pension Start Age",        min_value=0,   max_value=95,      value=0,     step=1,
                                        help="Age when DB pension begins. 0 = starts at your retirement age.")
        pt_income     = c10.number_input("Bridge Income ($/yr)",    min_value=0.0, max_value=200000.0, value=0.0,  step=1000.0,
                                         help="Part-time or contract income earned after retirement before fully stopping work.")
        pt_until      = c11.number_input("Bridge Income Until Age", min_value=0,   max_value=95,      value=0,     step=1,
                                         help="Age at which bridge income stops. 0 = no bridge income.")

        c12, c13, c14, c15 = st.columns(4)
        rrsp      = c12.number_input("RRSP/RRIF Balance ($)",    min_value=max(0.0, _rrsp_bal),    value=max(0.0, _rrsp_bal),    step=5_000.0, format="%.0f")
        tfsa      = c13.number_input("TFSA Balance ($)",          min_value=max(0.0, _tfsa_bal),    value=max(0.0, _tfsa_bal),    step=5_000.0, format="%.0f")
        non_reg   = c14.number_input("Non-Reg Balance ($)",       min_value=max(0.0, _non_reg_bal), value=max(0.0, _non_reg_bal), step=5_000.0, format="%.0f")
        tfsa_room = c15.number_input("TFSA Room Remaining ($)",   min_value=0.0, value=28_000.0,  step=500.0,   format="%.0f",
                                     help="Available TFSA contribution room. Check your CRA My Account or last NOA. New room of $7,000 is added each January.")

        st.markdown("**Spending**")
        s1, s2, s3 = st.columns(3)
        annual_spend = s1.number_input(
            "Annual Spending Target ($, today's dollars)",
            min_value=0.0, value=80_000.0, step=1_000.0, format="%.0f",
            help="Take-home spending — does NOT include voluntary TFSA contributions. "
                 "Enter those separately below.",
        )
        tfsa_topup   = s2.number_input(
            "Voluntary TFSA Top-up ($/yr, household)",
            min_value=0.0, max_value=14_000.0, value=0.0, step=500.0, format="%.0f",
            help="Household annual amount to deliberately withdraw from RRSP and shelter "
                 "in TFSA, on top of your spending target. Split evenly between spouses "
                 "(e.g. $7,000 = $3,500 per person). This is SEPARATE from auto-shelter: "
                 "auto-shelter only re-routes mandatory RRIF surplus (age 71+) that already "
                 "exists — it never forces an extra withdrawal. Both share the same annual "
                 "TFSA room; any overflow goes to non-registered.",
        )
        inflation    = s3.number_input("Inflation Rate (%)", min_value=0.0, max_value=10.0, value=2.5, step=0.1)

        # ── Large expenditures ─────────────────────────────────────────────
        st.markdown("**Spending Phases** *(optional)*")
        st.caption(
            "Spending typically declines in later retirement as travel and activity slow. "
            "Enter 0 for an age to disable that phase."
        )
        _sp1, _sp2, _sp3, _sp4 = st.columns(4)
        slow_go_age_inp  = _sp1.number_input("Slow-Go Start Age",        min_value=0, max_value=95, value=70, step=1,
                                              key="slow_go_age", help="Age spending steps down (typically 70). Set 0 to disable.")
        slow_go_red_inp  = _sp2.number_input("Slow-Go Reduction (%)",    min_value=0.0, max_value=50.0, value=15.0, step=1.0,
                                              key="slow_go_red", help="% reduction from base spending at Slow-Go age (e.g. 15 = spend 15% less).")
        no_go_age_inp    = _sp3.number_input("No-Go Start Age",          min_value=0, max_value=95, value=80, step=1,
                                              key="no_go_age", help="Age spending steps down further (typically 80). Set 0 to disable.")
        no_go_red_inp    = _sp4.number_input("No-Go Additional Reduction (%)", min_value=0.0, max_value=50.0, value=25.0, step=1.0,
                                              key="no_go_red", help="Additional % reduction at No-Go age (stacks on Slow-Go).")
        if slow_go_age_inp > 0 or no_go_age_inp > 0:
            _ex_spend = float(spending.get("annual_target", 80_000) if False else 0) # preview only in profile context
            st.caption(
                f"Example on $80,000 base: "
                + (f"${80_000 * (1 - slow_go_red_inp/100):,.0f}/yr from age {slow_go_age_inp}  " if slow_go_age_inp > 0 else "")
                + (f"→ ${80_000 * (1 - slow_go_red_inp/100) * (1 - no_go_red_inp/100):,.0f}/yr from age {no_go_age_inp}" if no_go_age_inp > 0 else "")
            )

        st.markdown("**One-Time Large Expenditures** *(optional)*")
        st.caption(
            "Enter planned large expenses (car purchase, home renovation, travel, etc.). "
            "These are drawn from the portfolio in full in the year they occur."
        )
        _exp_count = st.number_input(
            "Number of large expenditures", min_value=0, max_value=10, value=0, step=1,
            key="large_exp_count",
        )
        large_expenditures = []
        if _exp_count > 0:
            _exp_cols = st.columns(2)
            for _i in range(int(_exp_count)):
                _ea, _eb = st.columns(2)
                _exp_age  = _ea.number_input(f"Expenditure {_i+1} — Age",    min_value=18, max_value=95, value=70, step=1,
                                              key=f"exp_age_{_i}")
                _exp_amt  = _eb.number_input(f"Expenditure {_i+1} — Amount ($)", min_value=0.0, value=25_000.0, step=1_000.0,
                                              format="%.0f", key=f"exp_amt_{_i}")
                if _exp_amt > 0:
                    large_expenditures.append({"age": int(_exp_age), "amount": float(_exp_amt)})

        spouse_data = {}
        if has_spouse:
            st.markdown("**Spouse**")
            cs1, cs2, cs3 = st.columns(3)
            sp_age        = cs1.number_input("Spouse Current Age",      min_value=18, max_value=95,      value=62,      step=1)
            sp_ret_age    = cs2.number_input("Spouse Retirement Age",   min_value=18, max_value=95,      value=65,      step=1,
                                             help="Age when spouse stops working. Their employment income flows until this age.")
            sp_employment = cs3.number_input("Spouse Employment Income ($/yr)", min_value=0.0, max_value=300000.0, value=0.0, step=1000.0,
                                             help="Spouse's annual employment income until their retirement age. Reduces portfolio draw.")

            cs4, cs5, cs6, cs7 = st.columns(4)
            sp_cpp        = cs4.number_input("Spouse CPP at 65 ($/mo)", min_value=0.0, max_value=1400.0, value=900.0,  step=50.0)
            sp_cpp_start  = cs5.number_input("Spouse CPP Start Age",    min_value=60,  max_value=70,     value=65,     step=1,
                                             help="Age spouse plans to start CPP.")
            sp_oas        = cs6.number_input("Spouse OAS at 65 ($/mo)", min_value=0.0, max_value=800.0,  value=650.0,  step=10.0)
            sp_oas_start  = cs7.number_input("Spouse OAS Start Age",    min_value=65,  max_value=70,     value=65,     step=1,
                                             help="Age spouse plans to start OAS.")

            cs8, cs9, cs10, cs11 = st.columns(4)
            sp_rrsp      = cs8.number_input("Spouse RRSP/RRIF ($)",         min_value=0.0, value=120_000.0, step=5_000.0, format="%.0f")
            sp_tfsa      = cs9.number_input("Spouse TFSA ($)",              min_value=0.0, value=45_000.0,  step=5_000.0, format="%.0f")
            sp_non       = cs10.number_input("Spouse Non-Reg ($)",          min_value=0.0, value=30_000.0,  step=5_000.0, format="%.0f")
            sp_tfsa_room = cs11.number_input("Spouse TFSA Room ($)",        min_value=0.0, value=20_000.0,  step=500.0,   format="%.0f",
                                             help="Spouse's available TFSA contribution room.")

            spouse_data = {
                "current_age":            sp_age,
                "retirement_age":         int(sp_ret_age),
                "province":               province,
                "cpp_monthly_at_65":      sp_cpp,
                "cpp_start_age":          int(sp_cpp_start),
                "oas_monthly_at_65":      sp_oas,
                "oas_start_age":          int(sp_oas_start),
                "pension_monthly":        0.0,
                "rrsp_rrif_balance":      sp_rrsp,
                "tfsa_balance":           sp_tfsa,
                "non_registered_balance": sp_non,
                "tfsa_room_remaining":    sp_tfsa_room,
                "part_time_income":       sp_employment,
                "part_time_until_age":    int(sp_ret_age) - 1 if sp_employment > 0 else 0,
            }

        st.markdown("**Preferences**")
        auto_tfsa = st.checkbox(
            "Auto-shelter RRIF excess into TFSA (recommended)",
            value=True,
            help="After age 71, RRIF mandatory minimums may force more income than you need to spend. "
                 "With this on, that surplus is deposited into TFSA (tax-free) up to available room, "
                 "then non-registered. It never forces an extra withdrawal — it only redirects income "
                 "that was coming out anyway. Does not conflict with the voluntary top-up above; "
                 "both share the same annual TFSA room.",
        )

        submitted = st.form_submit_button("Run Projection", type="primary")

    if not submitted:
        return None

    # Persist province so the selectbox remembers it on the next render
    st.session_state["rp_province"] = province

    profile = {
        "version": "1.0",
        "household": {
            "primary": {
                "current_age":            age,
                "retirement_age":         int(ret_age),
                "province":               province,
                "cpp_monthly_at_65":      cpp_mo,
                "cpp_start_age":          int(cpp_start),
                "oas_monthly_at_65":      oas_mo,
                "oas_start_age":          int(oas_start),
                "pension_monthly":        pension,
                "pension_start_age":      int(pension_start),
                "rrsp_rrif_balance":      rrsp,
                "tfsa_balance":           tfsa,
                "non_registered_balance": non_reg,
                "tfsa_room_remaining":    tfsa_room,
                "part_time_income":       pt_income,
                "part_time_until_age":    int(pt_until),
            },
        },
        "preferences": {
            "auto_tfsa_routing": auto_tfsa,
        },
        "spending": {
            "annual_target":        annual_spend,
            "voluntary_tfsa_topup": tfsa_topup,
            "inflation_rate_pct":   inflation,
            "large_expenditures":   large_expenditures,
            "slow_go_age":           int(slow_go_age_inp),
            "slow_go_reduction_pct": float(slow_go_red_inp),
            "no_go_age":             int(no_go_age_inp),
            "no_go_reduction_pct":   float(no_go_red_inp),
        },
    }
    if spouse_data:
        profile["household"]["spouse"] = spouse_data

    return profile


# ── Main ─────────────────────────────────────────────────────────────────────

def _breadcrumb(current: str) -> None:
    pages = [
        ("Hub",           "Home.py"),
        ("Portfolio",     "pages/1_Portfolio.py"),
        ("Analysis",      "pages/5_Analysis.py"),
        ("Wealth Builder","pages/6_WealthBuilder.py"),
        ("Retirement",    None),
    ]
    parts = [f"**{l}**" if l == current else (f"[{l}]({p})" if p else l) for l, p in pages]
    st.caption("  ›  ".join(parts))


def main():
    st.title("Retirement Planner")
    _breadcrumb("Retirement")
    st.caption(_DISCLAIMER)
    st.divider()

    # ── Load profile (from file if it exists, else form) ──────────────────
    file_profile = _load_profile()
    if file_profile:
        st.success(
            f"Loaded profile from `{PROFILE_PATH.relative_to(PROJECT_ROOT)}`. "
            "Edit the file to update your details, or use the form below to override."
        )
        with st.expander("Override profile with form inputs", expanded=False):
            form_profile = _profile_form()
    else:
        st.info(
            f"No `retirement_profile.yaml` found at `{PROFILE_PATH}`. "
            "Enter your details below to get started. "
            "Save the file to `data/retirement/retirement_profile.yaml` to persist between sessions."
        )
        form_profile = _profile_form()

    # Persist last-run profile in session state so widget interactions
    # (selectbox changes, tab clicks, etc.) don't reset the whole page.
    if form_profile is not None:
        st.session_state["last_profile"] = form_profile

    profile = form_profile or file_profile or st.session_state.get("last_profile")

    if profile is None:
        st.caption("Fill in the form above and click **Run Projection** to see your retirement outlook.")
        return

    # ── Extract profile components ─────────────────────────────────────────
    household = profile.get("household", {})
    primary_d = household.get("primary", {})
    spouse_d  = household.get("spouse")
    spending  = profile.get("spending", {})
    province  = primary_d.get("province", "ON")

    try:
        primary = _person_from_dict(primary_d, province)
        spouse  = _person_from_dict(spouse_d, province) if spouse_d else None
    except Exception as exc:
        st.error(f"Error reading profile data: {exc}")
        return

    base_year = datetime.now().year

    # ── Run scenarios ──────────────────────────────────────────────────────
    retirement_age   = int(primary_d.get("retirement_age", primary.current_age))
    cpp_start_age    = int(primary_d.get("cpp_start_age", 65))
    oas_start_age    = int(primary_d.get("oas_start_age", 65))
    sp_cpp_start_age = int(spouse_d.get("cpp_start_age", 0)) if spouse_d else 0
    sp_oas_start_age = int(spouse_d.get("oas_start_age", 0)) if spouse_d else 0
    auto_tfsa             = bool(profile.get("preferences", {}).get("auto_tfsa_routing", True))
    voluntary_topup       = float(spending.get("voluntary_tfsa_topup", 0.0))

    # ── Spending phases — adjustable in sidebar without re-submitting form ──
    _base_spending        = float(spending.get("annual_target", 80_000))
    _sg_age_saved         = int(spending.get("slow_go_age", 0))
    _sg_red_saved         = float(spending.get("slow_go_reduction_pct", 15.0))
    _ng_age_saved         = int(spending.get("no_go_age", 0))
    _ng_red_saved         = float(spending.get("no_go_reduction_pct", 25.0))

    with st.sidebar:
        st.divider()
        st.markdown("**Spending Phases**")
        st.caption("Adjust and see results update instantly.")
        _sg_on  = st.toggle("Slow-Go phase", value=(_sg_age_saved > 0), key="rt_sg_on")
        if _sg_on:
            slow_go_age           = st.slider("Slow-Go starts at age", 60, 85,
                                               value=_sg_age_saved if _sg_age_saved > 0 else 70,
                                               step=1, key="rt_sg_age")
            slow_go_reduction_pct = st.slider("Spending reduction (%)", 5, 40,
                                               value=int(_sg_red_saved), step=5, key="rt_sg_red")
            st.caption(f"→ ${_base_spending * (1 - slow_go_reduction_pct/100):,.0f}/yr from age {slow_go_age}")
        else:
            slow_go_age           = 0
            slow_go_reduction_pct = 15.0

        _ng_on  = st.toggle("No-Go phase", value=(_ng_age_saved > 0), key="rt_ng_on")
        if _ng_on:
            no_go_age             = st.slider("No-Go starts at age", 70, 90,
                                               value=_ng_age_saved if _ng_age_saved > 0 else 80,
                                               step=1, key="rt_ng_age")
            no_go_reduction_pct   = st.slider("Additional reduction (%)", 5, 40,
                                               value=int(_ng_red_saved), step=5, key="rt_ng_red")
            _sg_factor = (1 - slow_go_reduction_pct/100) if _sg_on else 1.0
            st.caption(f"→ ${_base_spending * _sg_factor * (1 - no_go_reduction_pct/100):,.0f}/yr from age {no_go_age}")
        else:
            no_go_age             = 0
            no_go_reduction_pct   = 25.0

    with st.spinner("Running projections..."):
        try:
            scenario_runs = _run_scenarios(
                primary, spouse, spending, province, base_year,
                retirement_age=retirement_age,
                cpp_start_age=cpp_start_age,
                oas_start_age=oas_start_age,
                sp_cpp_start_age=sp_cpp_start_age,
                sp_oas_start_age=sp_oas_start_age,
                auto_tfsa_routing=auto_tfsa,
                voluntary_tfsa_topup=voluntary_topup,
                slow_go_age=slow_go_age,
                slow_go_reduction_pct=slow_go_reduction_pct,
                no_go_age=no_go_age,
                no_go_reduction_pct=no_go_reduction_pct,
            )
        except Exception as exc:
            st.error(f"Projection error: {exc}")
            logger.exception("Retirement projection failed")
            return

    # ── Scenario selector (drives both Outlook metrics and Detail charts) ──
    sc_names = [sc.name for sc, _, _, _ in scenario_runs]
    if "chosen_scenario" not in st.session_state or st.session_state["chosen_scenario"] not in sc_names:
        st.session_state["chosen_scenario"] = sc_names[0]
    chosen = st.selectbox(
        "View scenario",
        sc_names,
        index=sc_names.index(st.session_state["chosen_scenario"]),
        key="chosen_scenario",
    )
    chosen_sc, chosen_rows, chosen_summary, chosen_dict = next(
        (sc, rows, summary, d) for sc, rows, summary, d in scenario_runs if sc.name == chosen
    )
    base_rows = scenario_runs[0][1]  # Base Case rows (for portfolio chart)

    st.subheader("Your Retirement Outlook")
    d1, d2, d3, d4, d5 = st.columns(5)

    annual_target = float(spending.get("annual_target", 80_000))
    d1.metric(
        "Annual Spending Target",
        _fmt_dollar(annual_target),
        help="Your target annual spending in today's dollars.",
    )

    dep_age       = chosen_summary.get("depletion_age")
    shortfall_yrs = chosen_summary.get("years_with_shortfall", 0)
    final_port    = chosen_summary.get("final_portfolio", 0)
    avg_cov       = chosen_summary.get("avg_coverage_pct", 100.0)
    min_cov       = chosen_summary.get("min_coverage_pct", 100.0)
    uncov_age     = chosen_summary.get("first_undercoverage_age")

    if dep_age and shortfall_yrs > 0:
        d2.metric("Portfolio Depletes", f"Age {dep_age}",
                  delta=f"⚠ {shortfall_yrs} shortfall years", delta_color="inverse")
    elif dep_age:
        d2.metric("Portfolio Depletes", f"Age {dep_age}",
                  delta="Guaranteed income covers spending", delta_color="off")
    elif final_port < 10_000:
        d2.metric("Portfolio at Age 95", _fmt_dollar(final_port),
                  delta="Essentially depleted by 95", delta_color="inverse")
    else:
        d2.metric("Portfolio at Age 95", _fmt_dollar(final_port),
                  delta="Fully intact", delta_color="normal")

    # Coverage metric
    if avg_cov >= 100.0:
        d3.metric("Goal Coverage", "100%",
                  delta="Fully covered to age 95", delta_color="normal")
    elif uncov_age:
        d3.metric("Goal Coverage", f"{avg_cov:.0f}% avg",
                  delta=f"Drops below 100% at age {uncov_age}", delta_color="inverse",
                  help=f"Average spending coverage across all retirement years. Worst year: {min_cov:.0f}%.")
    else:
        d3.metric("Goal Coverage", f"{avg_cov:.0f}%", delta_color="off")

    d4.metric(
        "Est. Total Taxes",
        _fmt_dollar(chosen_summary.get("total_taxes")),
        help="Cumulative estimated income taxes over the projection period.",
    )
    d5.metric(
        "Lifetime CPP + OAS",
        _fmt_dollar(chosen_summary.get("total_cpp_oas")),
        help="Total government income (CPP + OAS) received over the projection.",
    )

    st.divider()

    # ── Portfolio chart ────────────────────────────────────────────────────
    _portfolio_chart(scenario_runs)

    # ── Scenario comparison table ──────────────────────────────────────────
    st.subheader("Scenario Comparison")
    import pandas as pd
    comp_rows = []
    for sc, rows, summary, _ in scenario_runs:
        dep = summary["depletion_age"]
        shortfall = summary["years_with_shortfall"]
        if dep and shortfall > 0:
            portfolio_status = f"Depletes age {dep} ({shortfall} shortfall yrs)"
        elif dep:
            portfolio_status = f"Depletes age {dep} — income covers spending"
        else:
            portfolio_status = f"Intact · {_fmt_dollar(summary['final_portfolio'])} at 95"
        cov = summary.get("avg_coverage_pct", 100.0)
        uncov = summary.get("first_undercoverage_age")
        cov_str = "100% ✓" if cov >= 100.0 else f"{cov:.0f}% (drops age {uncov})" if uncov else f"{cov:.0f}%"
        comp_rows.append({
            "Scenario":         sc.name,
            "Return (%)":       f"{sc.portfolio_return_pct:.1f}%",
            "Inflation (%)":    f"{sc.inflation_rate_pct:.1f}%",
            "CPP / OAS Start":  f"{sc.cpp_start_age} / {sc.oas_start_age}",
            "Goal Coverage":    cov_str,
            "Portfolio":        portfolio_status,
            "Total Taxes":      _fmt_dollar(summary["total_taxes"]),
        })
    st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)

    st.divider()
    _tax_efficiency_panel(scenario_runs, province, base_year)

    st.divider()

    # ── Per-scenario detailed charts ───────────────────────────────────────
    st.subheader("Scenario Detail")

    tab_waterfall, tab_accounts, tab_taxes = st.tabs(
        ["Income Waterfall", "Account Balances", "Tax Burden"]
    )
    with tab_waterfall:
        _income_waterfall_chart(chosen_rows, chosen, sc=chosen_sc)
    with tab_accounts:
        _account_balance_chart(chosen_rows, chosen, sc=chosen_sc)
    with tab_taxes:
        _tax_timeline_chart(chosen_rows, chosen, sc=chosen_sc)

    with st.expander("Year-by-Year Cashflow Detail", expanded=False):
        import pandas as pd
        cf_rows = []
        for r in chosen_rows:
            cov = (r.spending_delivered / r.spending_target * 100) if r.spending_target > 0 else None
            cf_rows.append({
                "Age":          r.age_primary,
                "Pension ($)":  _fmt_dollar(r.pension_income),
                "CPP ($)":      _fmt_dollar(r.cpp_income),
                "OAS ($)":      _fmt_dollar(r.oas_income),
                "RRIF Draw ($)":    _fmt_dollar(r.withdrawal_from_rrif),
                "Non-Reg Draw ($)": _fmt_dollar(r.withdrawal_from_non_reg),
                "TFSA Draw ($)":    _fmt_dollar(r.withdrawal_from_tfsa),
                "Target ($)":   _fmt_dollar(r.spending_target),
                "Delivered ($)": _fmt_dollar(r.spending_delivered),
                "Coverage":     f"{cov:.0f}%" if cov is not None else "—",
                "Taxes ($)":    _fmt_dollar(r.taxes_estimated),
                "Portfolio ($)": _fmt_dollar(r.portfolio_value),
            })
        st.dataframe(pd.DataFrame(cf_rows), use_container_width=True, hide_index=True)

    # ── CPP/OAS timing ────────────────────────────────────────────────────
    st.divider()
    _cpp_oas_timing_section(primary)

    # ── Phase 2: Tax efficiency ────────────────────────────────────────────
    st.divider()
    st.subheader("Tax Efficiency")

    tab_strategy, tab_clawback, tab_tfsa = st.tabs(
        ["Withdrawal Strategy", "OAS Clawback", "TFSA Room"]
    )
    with tab_strategy:
        _withdrawal_strategy_comparison(primary, spending, province, base_year)
    with tab_clawback:
        st.markdown("**OAS Clawback Exposure by Scenario**")
        st.caption(
            f"OAS clawback begins at net income above the threshold "
            f"(~$93,454 in 2026) at a rate of 15¢ per dollar. "
            "High RRIF withdrawals and/or large CPP/OAS income can trigger it."
        )
        _oas_clawback_alerts(scenario_runs)
    with tab_tfsa:
        _tfsa_room_section(primary, base_year)

    # ── Phase 4: Household — income splitting ─────────────────────────────
    if spouse is not None:
        st.divider()
        st.subheader("Household — Pension Income Splitting")
        st.caption(
            "CRA allows up to 50% of eligible pension income (RRIF withdrawals age 65+, "
            "DB pension, annuity) to be allocated to your spouse on your T1. "
            "CPP and OAS are not eligible — use the CPP sharing election at Service Canada separately."
        )
        from agents.ori_rp.household import compute_pension_split, find_optimal_split

        # Use first-year Base Case figures as illustration
        r0 = scenario_runs[0][1][0] if scenario_runs[0][1] else None
        if r0:
            primary_eligible = r0.rrsp_rrif_balance * 0.054  # approx RRIF min at 65
            primary_eligible = max(primary_eligible, r0.portfolio_withdrawal * 0.6)
            primary_other    = r0.cpp_income + r0.oas_income + r0.pension_income + r0.part_time_income
            sp_income_est    = (spouse.cpp_monthly_at_65 * 12 + spouse.oas_monthly_at_65 * 12
                               + spouse.pension_monthly * 12)

            sp_col1, sp_col2 = st.columns([1, 3])
            split_pct = sp_col1.slider(
                "Split % (0–50)", min_value=0, max_value=50, value=25, step=5,
                key="split_pct_slider",
            )

            split_result = compute_pension_split(
                primary_eligible_pension=primary_eligible,
                primary_other_income=primary_other,
                spouse_income=sp_income_est,
                split_pct=float(split_pct),
                province=province,
                year=base_year,
            )

            with sp_col2:
                sc1, sc2, sc3 = st.columns(3)
                sc1.metric("Split Amount", f"${split_result['split_amount']:,.0f}")
                sc2.metric(
                    "Combined Tax — Before", f"${split_result['combined_tax_before']:,.0f}"
                )
                sc3.metric(
                    "Combined Tax — After",
                    f"${split_result['combined_tax_after']:,.0f}",
                    delta=f"-${split_result['tax_savings']:,.0f}" if split_result['tax_savings'] > 0 else "No saving",
                    delta_color="inverse",
                )

            st.caption(split_result["optimal_split_hint"])

            # Find optimal
            optimal = find_optimal_split(
                primary_eligible_pension=primary_eligible,
                primary_other_income=primary_other,
                spouse_income=sp_income_est,
                province=province,
                year=base_year,
            )
            if optimal["optimal_split_pct"] != split_pct:
                st.info(
                    f"Optimal split: **{optimal['optimal_split_pct']:.0f}%** "
                    f"saves **${optimal['tax_savings']:,.0f}** in estimated taxes "
                    f"(vs ${split_result['tax_savings']:,.0f} at {split_pct}%)."
                )
            st.caption(
                "Note: These are first-year illustrations using approximated eligible pension amounts. "
                "Actual eligible amounts and tax savings will vary by year as RRIF minimums change. "
                "Consult your tax advisor before electing pension income splitting on your T1."
            )

    # ── Phase 4: Readiness score ──────────────────────────────────────────
    st.divider()
    st.subheader("Retirement Readiness Score")
    mc_prob = st.session_state.get("mc_result", {}).get("prob_success") if "mc_result" in st.session_state else None

    try:
        from agents.ori_rp.readiness import compute_readiness_score
        readiness = compute_readiness_score(
            primary_age=primary.current_age,
            rrsp_rrif_balance=primary.rrsp_rrif_balance,
            tfsa_balance=primary.tfsa_balance,
            non_reg_balance=primary.non_registered_balance,
            tfsa_room_remaining=primary.tfsa_room_remaining,
            cpp_monthly_at_65=primary.cpp_monthly_at_65,
            oas_monthly_at_65=primary.oas_monthly_at_65,
            pension_monthly=primary.pension_monthly,
            cpp_start_age=scenario_runs[0][0].cpp_start_age,
            oas_start_age=scenario_runs[0][0].oas_start_age,
            annual_spending=float(spending.get("annual_target", 80_000)),
            province=province,
            base_year=base_year,
            longevity_age=95,
            mc_prob_success=mc_prob,
            spouse=spouse,
            sp_cpp_start_age=scenario_runs[0][0].sp_cpp_start_age,
            sp_oas_start_age=scenario_runs[0][0].sp_oas_start_age,
        )

        rs_col1, rs_col2 = st.columns([1, 3])
        score = readiness["score"]
        label = readiness["label"]
        colour = {"Excellent": "normal", "Good": "normal", "Fair": "off",
                  "At Risk": "inverse", "Critical": "inverse"}.get(label, "off")
        rs_col1.metric(f"Readiness Score", f"{score:.0f} / 100", delta=label, delta_color=colour)

        with rs_col2:
            import pandas as pd
            comp_df = pd.DataFrame(readiness["components"])
            comp_df["Max"] = comp_df["weight"]
            comp_df = comp_df[["name", "score", "Max", "detail"]]
            comp_df.columns = ["Component", "Score", "Max", "Detail"]
            comp_df["Score"] = comp_df["Score"].map(lambda v: f"{v:.1f}")
            st.dataframe(comp_df, use_container_width=True, hide_index=True)

        st.caption(readiness["disclaimer"])
    except Exception as exc:
        st.warning(f"Readiness score unavailable: {exc}")

    # ── Phase 3: Monte Carlo ──────────────────────────────────────────────
    st.divider()
    st.subheader("Monte Carlo Analysis")
    st.caption(
        "Randomizes annual portfolio returns across 500 simulations to show the range "
        "of outcomes. The shaded band is P10–P90; the solid line is the median (P50). "
        "Probability of success = fraction of simulations where portfolio > 0 at your "
        "planning horizon."
    )

    try:
        from agents.ori_rp.monte_carlo import run_monte_carlo, asset_mix_options
        _mc_available = True
    except ImportError:
        _mc_available = False
        st.warning("numpy not installed. Run: pip install numpy")

    if _mc_available:
        mc_col1, mc_col2, mc_col3 = st.columns([2, 2, 2])
        mc_scenario_name = mc_col1.selectbox(
            "Scenario", [sc.name for sc, _, _, _ in scenario_runs],
            index=0, key="mc_scenario",
        )
        mc_asset_mix = mc_col2.selectbox(
            "Asset Mix", asset_mix_options(), index=1, key="mc_mix",
            help="Sets the volatility (σ) used in the simulation. Balanced = 12% σ."
        )
        mc_n_sims = mc_col3.select_slider(
            "Simulations", options=[100, 250, 500, 1000], value=500, key="mc_n_sims",
        )

        if st.button("Run Monte Carlo", type="primary", key="mc_run"):
            mc_sc, mc_rows, mc_summary, _ = next(
                (sc, rows, s, d) for sc, rows, s, d in scenario_runs
                if sc.name == mc_scenario_name
            )
            with st.spinner(f"Running {mc_n_sims} simulations..."):
                try:
                    mc_result = run_monte_carlo(
                        deterministic_rows=mc_rows,
                        mu=mc_sc.portfolio_return_pct,
                        asset_mix=mc_asset_mix,
                        n_sims=mc_n_sims,
                        seed=42,
                    )
                    st.session_state["mc_result"]      = mc_result
                    st.session_state["mc_scenario_run"] = (mc_sc, mc_rows, mc_summary)
                except Exception as exc:
                    st.error(f"Monte Carlo error: {exc}")
                    logger.exception("Monte Carlo failed")

        if "mc_result" in st.session_state:
            mc_result = st.session_state["mc_result"]
            mc_sc, mc_rows, mc_summary = st.session_state["mc_scenario_run"]

            # Key metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(
                "Probability of Success",
                f"{mc_result['prob_success']:.1f}%",
                help=f"Portfolio survives to age {mc_sc.longevity_age} in "
                     f"{mc_result['prob_success']:.1f}% of {mc_result['n_sims']} simulations.",
            )
            _ages = mc_result.get("ages", [])
            _p50_zero_age = _mc_first_zero_age(mc_result["p50"], _ages) if mc_result.get("p50") else None
            _p10_zero_age = _mc_first_zero_age(mc_result["p10"], _ages) if mc_result.get("p10") else None

            m2.metric(
                "Median Final Balance (P50)",
                _fmt_dollar(mc_result["p50"][-1] if mc_result["p50"] else None),
                delta=f"Depletes age {_p50_zero_age}" if _p50_zero_age else None,
                delta_color="off",
            )
            m3.metric(
                "Pessimistic Final Balance (P10)",
                _fmt_dollar(mc_result["p10"][-1] if mc_result["p10"] else None),
                delta=f"Depletes age {_p10_zero_age}" if _p10_zero_age else None,
                delta_color="off",
            )
            m4.metric(
                "Optimistic Final Balance (P90)",
                _fmt_dollar(mc_result["p90"][-1] if mc_result["p90"] else None),
            )

            _monte_carlo_chart(mc_result, mc_sc.name)

            if mc_result["prob_success"] < 70:
                st.error(
                    f"⚠ Only {mc_result['prob_success']:.1f}% of simulations are successful. "
                    "Consider reducing spending, deferring CPP/OAS, or reviewing your asset mix."
                )
            elif mc_result["prob_success"] < 85:
                st.warning(
                    f"Probability of success: {mc_result['prob_success']:.1f}%. "
                    "This is below the commonly recommended 85%+ threshold for retirement plans."
                )
            else:
                st.success(
                    f"Probability of success: {mc_result['prob_success']:.1f}%. "
                    "Portfolio appears resilient to return variability."
                )

    # ── Phase 3: Annual review checklist ─────────────────────────────────
    st.divider()
    st.subheader("Annual Review Checklist")

    from agents.ori_rp.report import annual_review_checklist

    cpp_started = primary.current_age >= scenario_runs[0][0].cpp_start_age
    oas_started = primary.current_age >= scenario_runs[0][0].oas_start_age
    oas_clawback_any = any(
        any(r.oas_clawback > 0 for r in rows)
        for _, rows, _, _ in scenario_runs
    )

    checklist_md = annual_review_checklist(
        primary_age=primary.current_age,
        rrsp_rrif_balance=primary.rrsp_rrif_balance,
        tfsa_room_remaining=primary.tfsa_room_remaining,
        cpp_start_age=scenario_runs[0][0].cpp_start_age,
        oas_start_age=scenario_runs[0][0].oas_start_age,
        cpp_started=cpp_started,
        oas_started=oas_started,
        oas_clawback_risk=oas_clawback_any,
        province=province,
        year=base_year,
    )
    with st.expander("View checklist", expanded=True):
        st.markdown(checklist_md)

    st.download_button(
        label="Download Checklist (.md)",
        data=checklist_md.encode(),
        file_name=f"annual_review_{base_year}.md",
        mime="text/markdown",
        key="dl_checklist",
    )

    # ── Phase 3: Download report ──────────────────────────────────────────
    st.divider()
    st.subheader("Plan Summary Report")

    from agents.ori_rp.report import one_page_summary

    base_sc, base_rows_rpt, base_summary_rpt, base_dict_rpt = scenario_runs[0]
    mc_for_report = st.session_state.get("mc_result") if "mc_result" in st.session_state else None
    if mc_for_report and st.session_state.get("mc_scenario_run", (None,))[0] != base_sc:
        mc_for_report = None  # only attach MC to report if it matches Base Case

    report_md = one_page_summary(
        scenario_name=base_sc.name,
        params_dict=base_dict_rpt.get("parameters", {}),
        summary=base_summary_rpt,
        rows=base_rows_rpt,
        primary_age=primary.current_age,
        province=province,
        mc_result=mc_for_report,
        year=base_year,
    )

    col_report1, col_report2 = st.columns([1, 3])
    col_report1.download_button(
        label="Download Report (.md)",
        data=report_md.encode(),
        file_name=f"retirement_plan_{base_year}.md",
        mime="text/markdown",
        key="dl_report",
    )
    col_report2.caption(
        "Markdown report includes scenario parameters, portfolio longevity, "
        "5-year withdrawal plan, Monte Carlo results (if run), and key risks. "
        "Open in any Markdown viewer or paste into your notes app."
    )

    # ── Save scenario JSON ─────────────────────────────────────────────────
    st.divider()
    st.subheader("Save Scenario")
    col_save, col_note = st.columns([1, 3])
    if col_save.button("Save Base Case JSON", type="secondary"):
        try:
            saved_path = _save_scenario(base_dict_rpt, base_sc.name)
            col_note.success(f"Saved to `{saved_path.relative_to(PROJECT_ROOT)}`")
        except Exception as exc:
            col_note.error(f"Save failed: {exc}")

    # ── Handoff banner ────────────────────────────────────────────────────
    st.divider()
    _rh1, _rh2 = st.columns(2)
    _rh1.page_link("pages/1_Portfolio.py",   label="← Portfolio IA — what do I own?")
    _rh2.page_link("pages/6_WealthBuilder.py", label="← Wealth Builder — am I on track?")

    # ── Disclaimer footer ──────────────────────────────────────────────────
    st.divider()
    st.markdown(_DISCLAIMER)


if __name__ == "__main__":
    main()
else:
    main()
