"""
pages/7_WealthBuilder.py
------------------------
Auri Wealth Builder — accumulation-phase financial planning.

Five pillars:
  1. RRSP vs TFSA Optimizer  — marginal-tax contribution strategy
  2. Savings Projector        — savings rate → FI number → retirement age
  3. Asset Allocation         — glide-path model by horizon + risk tolerance
  4. Rebalancer               — portfolio drift detection + trade guidance
  5. Net Worth                — balance sheet (Kubera-style assets − liabilities)

Profile stored at data/wealth/wealth_profile.yaml (gitignored).

Disclaimer: All figures are for planning and educational purposes only.
Consult a registered financial advisor before making investment decisions.
"""

from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Wealth Builder — Auri",
    layout="wide",
    initial_sidebar_state="expanded",
)

PROJECT_ROOT  = Path(__file__).resolve().parent.parent
PROFILE_PATH  = PROJECT_ROOT / "data" / "wealth" / "wealth_profile.yaml"
PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)

try:
    import plotly.graph_objects as go
    import plotly.express as px
    _PLOTLY = True
except ImportError:
    _PLOTLY = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(v: float) -> str:
    return f"${v:,.0f}"


def _save_profile(data: dict) -> None:
    import yaml
    with PROFILE_PATH.open("w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def _load_profile() -> dict:
    if not PROFILE_PATH.exists():
        return {}
    import yaml
    return yaml.safe_load(PROFILE_PATH.read_text()) or {}


# ── Tab 1: RRSP vs TFSA Optimizer ─────────────────────────────────────────────

def _tab_optimizer(profile: dict) -> None:
    st.subheader("RRSP vs TFSA Contribution Optimizer")
    st.caption(
        "Determines the tax-optimal split between RRSP and TFSA for this year's savings "
        "based on your marginal rate today vs your expected rate in retirement."
    )

    pref = profile.get("preferences", {})
    fin  = profile.get("financials", {})

    with st.form("optimizer_form"):
        c1, c2, c3 = st.columns(3)
        gross_income   = c1.number_input("Gross Annual Income ($)", min_value=0, max_value=1_000_000,
                                          value=int(fin.get("gross_income", 95_000)), step=1_000)
        savings_amount = c2.number_input("Amount to Contribute This Year ($)", min_value=0, max_value=500_000,
                                          value=int(fin.get("annual_savings", 15_000)), step=500)
        province       = c3.selectbox("Province", ["BC", "AB", "ON", "QC", "SK", "MB", "NS", "NB", "PE", "NL"],
                                       index=["BC","AB","ON","QC","SK","MB","NS","NB","PE","NL"].index(
                                           pref.get("province", "BC")))

        c4, c5, c6 = st.columns(3)
        rrsp_room      = c4.number_input("RRSP Room Remaining ($)", min_value=0, max_value=500_000,
                                          value=int(fin.get("rrsp_room", 50_000)), step=1_000,
                                          help="From your CRA My Account or most recent NOA.")
        tfsa_room      = c5.number_input("TFSA Room Remaining ($)", min_value=0, max_value=200_000,
                                          value=int(fin.get("tfsa_room", 30_000)), step=500,
                                          help="Total unused TFSA contribution room.")
        ret_income     = c6.number_input("Expected Retirement Income ($)", min_value=0, max_value=500_000,
                                          value=int(fin.get("expected_retirement_income", 55_000)), step=1_000,
                                          help="Estimated gross income in retirement (CPP + OAS + RRIF withdrawals).")

        c7, c8 = st.columns(2)
        yrs_to_ret = c7.number_input("Years to Retirement", min_value=1, max_value=50,
                                      value=int(fin.get("years_to_retirement", 20)), step=1)
        growth_rate = c8.number_input("Expected Annual Return (%)", min_value=0.0, max_value=15.0,
                                       value=float(fin.get("growth_rate_pct", 6.0)), step=0.5)

        submitted = st.form_submit_button("Calculate", type="primary", use_container_width=True)

    if not submitted:
        return

    from agents.ori_wb.optimizer import OptimizerInput, optimise
    inp = OptimizerInput(
        gross_income                = float(gross_income),
        savings_available           = float(savings_amount),
        rrsp_room_remaining         = float(rrsp_room),
        tfsa_room_remaining         = float(tfsa_room),
        province                    = province,
        current_year                = 2026,
        expected_retirement_income  = float(ret_income),
        growth_rate                 = float(growth_rate) / 100.0,
        years_to_retirement         = int(yrs_to_ret),
    )
    result = optimise(inp)

    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Recommended RRSP", _fmt(result.recommended_rrsp))
    m2.metric("Recommended TFSA", _fmt(result.recommended_tfsa))
    m3.metric("Immediate Tax Saving", _fmt(result.rrsp_tax_saving),
              help="Estimated refund from RRSP deduction at your marginal rate.")
    if result.surplus_unregistered > 0:
        m4.metric("Non-Registered Overflow", _fmt(result.surplus_unregistered),
                  help="Exceeds both account rooms — invest in a taxable account.")
    else:
        m4.metric("Unallocated", _fmt(0))

    st.info(result.rationale)

    r1, r2 = st.columns(2)
    with r1:
        st.markdown("**Rate Comparison**")
        rc1, rc2 = st.columns(2)
        rc1.metric("Marginal Rate Today", f"{result.marginal_rate_now:.1%}")
        rc2.metric("Est. Retirement Rate", f"{result.marginal_rate_retirement:.1%}",
                   delta=f"{result.marginal_rate_retirement - result.marginal_rate_now:+.1%}",
                   delta_color="inverse")

    with r2:
        st.markdown(f"**Projected Value at Retirement ({yrs_to_ret} years)**")
        pv1, pv2 = st.columns(2)
        pv1.metric("RRSP (after-tax withdrawal)", _fmt(result.rrsp_future_value),
                   help="Gross RRSP value × (1 - estimated retirement marginal rate)")
        pv2.metric("TFSA (tax-free)", _fmt(result.tfsa_future_value))

    if result.rrsp_capped_by_room:
        st.warning(f"RRSP room is the binding constraint at {_fmt(rrsp_room)}. Consider maximising TFSA with the remainder.")
    if result.tfsa_capped_by_room:
        st.warning(f"TFSA room is the binding constraint at {_fmt(tfsa_room)}. Consider non-registered investing for the surplus.")

    if _PLOTLY and (result.recommended_rrsp > 0 or result.recommended_tfsa > 0):
        fig = go.Figure(go.Bar(
            x=["RRSP", "TFSA", "Non-Registered" if result.surplus_unregistered > 0 else None],
            y=[result.recommended_rrsp, result.recommended_tfsa,
               result.surplus_unregistered if result.surplus_unregistered > 0 else None],
            marker_color=["#2563EB", "#059669", "#9CA3AF"],
            text=[_fmt(v) for v in [result.recommended_rrsp, result.recommended_tfsa,
                                     result.surplus_unregistered]],
            textposition="outside",
        ))
        fig.update_layout(
            title="Recommended Contribution Split",
            yaxis_tickformat="$,.0f",
            height=320,
            margin=dict(l=0, r=0, t=50, b=0),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)


# ── Tab 2: Savings Projector ───────────────────────────────────────────────────

def _tab_projector(profile: dict) -> None:
    st.subheader("Savings Projector")
    st.caption(
        "Projects your nest egg from today to retirement and finds the age "
        "at which your portfolio reaches your Financial Independence (FI) number."
    )

    fin = profile.get("financials", {})

    with st.form("projector_form"):
        c1, c2, c3 = st.columns(3)
        current_age    = c1.number_input("Current Age", min_value=18, max_value=70,
                                          value=int(fin.get("current_age", 35)), step=1)
        target_ret_age = c2.number_input("Target Retirement Age", min_value=40, max_value=75,
                                          value=int(fin.get("target_retirement_age", 60)), step=1)
        current_savings = c3.number_input("Current Total Savings ($)", min_value=0, max_value=5_000_000,
                                           value=int(fin.get("current_savings", 150_000)), step=5_000)

        c4, c5, c6 = st.columns(3)
        annual_income   = c4.number_input("Gross Annual Income ($)", min_value=0, max_value=1_000_000,
                                           value=int(fin.get("gross_income", 95_000)), step=1_000)
        savings_rate    = c5.number_input("Savings Rate (% of income)", min_value=0.0, max_value=80.0,
                                           value=float(fin.get("savings_rate_pct", 20.0)), step=1.0)
        expected_return = c6.number_input("Expected Annual Return (%)", min_value=0.0, max_value=15.0,
                                           value=float(fin.get("growth_rate_pct", 6.0)), step=0.5)

        c7, c8, c9 = st.columns(3)
        inflation   = c7.number_input("Inflation (%)", min_value=0.0, max_value=10.0,
                                       value=float(fin.get("inflation_pct", 2.5)), step=0.1)
        fi_multiple = c8.number_input("FI Multiple (×)", min_value=10.0, max_value=40.0,
                                       value=float(fin.get("fi_multiple", 25.0)), step=1.0,
                                       help="FI target = annual spending × this multiple (25 = 4% SWR).")
        annual_spend = c9.number_input("Annual Spending ($, 0 = derive from savings rate)", min_value=0,
                                        max_value=500_000, value=0, step=1_000)

        submitted = st.form_submit_button("Project", type="primary", use_container_width=True)

    if not submitted:
        return

    from agents.ori_wb.projector import ProjectorInput, project
    inp = ProjectorInput(
        current_age           = int(current_age),
        current_savings       = float(current_savings),
        annual_income         = float(annual_income),
        savings_rate_pct      = float(savings_rate),
        expected_return_pct   = float(expected_return),
        inflation_pct         = float(inflation),
        target_retirement_age = int(target_ret_age),
        fi_multiple           = float(fi_multiple),
        annual_spending       = float(annual_spend),
    )
    result = project(inp)

    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Nest Egg at Target Age", _fmt(result.balance_at_target))
    m2.metric("FI Number at Target Age", _fmt(result.fi_number_at_target))
    if result.shortfall_at_target > 0:
        m3.metric("Shortfall", _fmt(result.shortfall_at_target), delta=f"-{_fmt(result.shortfall_at_target)}", delta_color="inverse")
    else:
        m3.metric("Surplus", _fmt(-result.shortfall_at_target), delta=f"+{_fmt(-result.shortfall_at_target)}", delta_color="normal")
    if result.fi_age:
        m4.metric("FI Age", str(result.fi_age),
                  delta=f"{result.fi_age - int(target_ret_age):+d} vs target",
                  delta_color="normal" if result.fi_age <= int(target_ret_age) else "inverse")
    else:
        m4.metric("FI Age", "Not reached", delta="Increase savings or return", delta_color="inverse")

    # ── Chart: balance vs FI number ───────────────────────────────────────
    if _PLOTLY:
        ages     = [r.age     for r in result.rows]
        balances = [r.balance for r in result.rows]
        fi_nums  = [r.fi_number for r in result.rows]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=ages, y=balances, name="Projected Balance",
            line=dict(color="#2563EB", width=2.5),
            fill="tozeroy", fillcolor="rgba(37,99,235,0.08)",
            hovertemplate="Age %{x}<br>Balance: $%{y:,.0f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=ages, y=fi_nums, name="FI Number",
            line=dict(color="#DC2626", width=2, dash="dash"),
            hovertemplate="Age %{x}<br>FI Target: $%{y:,.0f}<extra></extra>",
        ))
        # Retirement target line
        fig.add_vline(x=int(target_ret_age), line=dict(color="#6B7280", dash="dot", width=1.5),
                      annotation_text="Target retirement", annotation_position="top right",
                      annotation_font_size=11)
        if result.fi_age:
            fig.add_vline(x=result.fi_age, line=dict(color="#059669", dash="dash", width=1.5),
                          annotation_text=f"FI age {result.fi_age}", annotation_position="top left",
                          annotation_font_size=11, annotation_font_color="#059669")

        fig.update_layout(
            title="Projected Wealth vs FI Number",
            xaxis_title="Age",
            yaxis_title="Portfolio Value ($)",
            yaxis_tickformat="$,.0f",
            hovermode="x unified",
            height=400,
            margin=dict(l=0, r=0, t=60, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Sensitivity table ─────────────────────────────────────────────────
    st.markdown("**Sensitivity Analysis**")
    import pandas as pd
    rows_data = []
    for s in result.sensitivity:
        rows_data.append({
            "Scenario":         s["scenario"],
            "Return":           f"{s['return_pct']:.1f}%",
            "Savings Rate":     f"{s['savings_rate_pct']:.1f}%",
            "Balance at Target": _fmt(s["balance_at_target"]),
            "FI Number":        _fmt(s["fi_number"]),
            "Shortfall / Surplus": _fmt(abs(s["shortfall"])) + (" surplus" if s["shortfall"] < 0 else " shortfall"),
            "FI Age":           str(s["fi_age"]) if s["fi_age"] else "—",
        })
    st.dataframe(pd.DataFrame(rows_data), use_container_width=True, hide_index=True)


# ── Tab 3: Asset Allocation ────────────────────────────────────────────────────

def _tab_allocation(profile: dict) -> None:
    st.subheader("Asset Allocation by Horizon")
    st.caption(
        "Recommends a target split between equities, bonds/GICs, and cash "
        "based on your time horizon and risk tolerance."
    )

    fin  = profile.get("financials", {})
    pref = profile.get("preferences", {})

    c1, c2, c3 = st.columns(3)
    yrs_to_ret  = c1.number_input("Years to Retirement", min_value=0, max_value=50,
                                   value=int(fin.get("years_to_retirement", 20)), step=1, key="alloc_yrs")
    risk        = c2.selectbox("Risk Tolerance", ["conservative", "moderate", "aggressive"],
                                index=["conservative","moderate","aggressive"].index(
                                    pref.get("risk_tolerance", "moderate")), key="alloc_risk")
    threshold   = c3.number_input("Rebalance Threshold (pp)", min_value=1.0, max_value=20.0,
                                   value=5.0, step=1.0, key="alloc_thresh",
                                   help="Flag drift if any bucket moves more than this many percentage points from target.")

    from agents.ori_wb.allocation import target_allocation, all_risk_targets
    tgt  = target_allocation(int(yrs_to_ret), risk)  # type: ignore[arg-type]
    all_tgts = all_risk_targets(int(yrs_to_ret))

    st.divider()
    st.markdown(f"**Target allocation — {risk.capitalize()} · {yrs_to_ret} years to retirement**")
    a1, a2, a3 = st.columns(3)
    a1.metric("Equities (Growth)",         f"{tgt.equities_pct:.0f}%")
    a2.metric("Bonds / GICs (Stability)",  f"{tgt.bonds_pct:.0f}%")
    a3.metric("Cash / HISA (Liquidity)",   f"{tgt.cash_pct:.0f}%")

    if _PLOTLY:
        # Donut for target
        fig = go.Figure(go.Pie(
            labels=["Equities", "Bonds / GICs", "Cash"],
            values=[tgt.equities_pct, tgt.bonds_pct, tgt.cash_pct],
            hole=0.45,
            marker_colors=["#2563EB", "#7C3AED", "#059669"],
            textinfo="label+percent",
            hovertemplate="%{label}: %{value:.0f}%<extra></extra>",
        ))
        fig.update_layout(
            title=f"Target Allocation ({risk.capitalize()})",
            height=320,
            margin=dict(l=0, r=0, t=50, b=0),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── All risk levels comparison ─────────────────────────────────────────
    with st.expander("Compare all risk levels"):
        import pandas as pd
        comp = []
        for r, t in all_tgts.items():
            comp.append({
                "Risk Tolerance": r.capitalize(),
                "Equities (%)": f"{t.equities_pct:.0f}%",
                "Bonds / GICs (%)": f"{t.bonds_pct:.0f}%",
                "Cash (%)": f"{t.cash_pct:.0f}%",
            })
        st.dataframe(pd.DataFrame(comp), use_container_width=True, hide_index=True)

    # ── Optional: current allocation checkup ──────────────────────────────
    st.divider()
    st.markdown("**Optional: Check Your Current Allocation**")
    st.caption("Enter your current allocation below to see drift from target.")
    with st.form("allocation_checkup_form"):
        b1, b2, b3 = st.columns(3)
        cur_eq   = b1.number_input("Current Equities (%)", 0.0, 100.0, value=70.0, step=1.0)
        cur_bond = b2.number_input("Current Bonds / GICs (%)", 0.0, 100.0, value=25.0, step=1.0)
        cur_cash = b3.number_input("Current Cash (%)", 0.0, 100.0, value=5.0, step=1.0)
        check = st.form_submit_button("Check Drift", use_container_width=True)

    if check:
        from agents.ori_wb.allocation import allocation_checkup
        ck = allocation_checkup(
            int(yrs_to_ret), risk,  # type: ignore[arg-type]
            float(cur_eq), float(cur_bond), float(cur_cash),
            float(threshold),
        )
        if ck.needs_rebalance:
            st.warning(f"Rebalancing suggested — max drift is {ck.max_drift:.1f} pp (threshold: {ck.rebalance_threshold:.0f} pp).")
        else:
            st.success(f"On target — max drift is {ck.max_drift:.1f} pp. No action needed.")

        import pandas as pd
        rows = [
            {"Bucket": "Equities",     "Current": f"{ck.current_equities:.1f}%", "Target": f"{ck.target.equities_pct:.0f}%", "Drift": f"{ck.drift_equities:+.1f} pp"},
            {"Bucket": "Bonds / GICs", "Current": f"{ck.current_bonds:.1f}%",    "Target": f"{ck.target.bonds_pct:.0f}%",    "Drift": f"{ck.drift_bonds:+.1f} pp"},
            {"Bucket": "Cash",         "Current": f"{ck.current_cash:.1f}%",     "Target": f"{ck.target.cash_pct:.0f}%",     "Drift": f"{ck.drift_cash:+.1f} pp"},
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Tab 4: Rebalancer ─────────────────────────────────────────────────────────

def _tab_rebalancer(profile: dict) -> None:
    st.subheader("Portfolio Rebalancer")
    st.caption(
        "Enter your current holdings (by asset class) to see drift from your target "
        "allocation and get rebalancing guidance."
    )

    fin  = profile.get("financials", {})
    pref = profile.get("preferences", {})

    # Target allocation inputs
    c1, c2 = st.columns(2)
    yrs_to_ret = c1.number_input("Years to Retirement", min_value=0, max_value=50,
                                  value=int(fin.get("years_to_retirement", 20)), step=1, key="reb_yrs")
    risk       = c2.selectbox("Risk Tolerance", ["conservative", "moderate", "aggressive"],
                               index=["conservative","moderate","aggressive"].index(
                                   pref.get("risk_tolerance", "moderate")), key="reb_risk")

    from agents.ori_wb.allocation import target_allocation
    tgt = target_allocation(int(yrs_to_ret), risk)  # type: ignore[arg-type]
    st.caption(f"Target: Equities {tgt.equities_pct:.0f}% / Bonds {tgt.bonds_pct:.0f}% / Cash {tgt.cash_pct:.0f}%")

    # ── Holdings input ────────────────────────────────────────────────────
    st.markdown("**Enter Holdings**")
    st.caption("Add each position's approximate market value and asset class. Use 'equity', 'bond', 'gic', or 'cash'.")

    # Try to pre-populate from Portfolio session state
    _portfolio_holdings = _get_portfolio_holdings()

    n_positions = st.number_input("Number of positions", min_value=1, max_value=20, value=max(3, len(_portfolio_holdings)), step=1)
    holdings_data = []

    with st.form("rebalancer_form"):
        for i in range(int(n_positions)):
            pre = _portfolio_holdings[i] if i < len(_portfolio_holdings) else {}
            r1, r2, r3 = st.columns([2, 2, 1])
            sym   = r1.text_input(f"Symbol / Name #{i+1}", value=pre.get("symbol", ""), key=f"reb_sym_{i}")
            val   = r2.number_input(f"Market Value ($) #{i+1}", min_value=0, max_value=5_000_000,
                                     value=int(pre.get("value", 0)), step=100, key=f"reb_val_{i}")
            ac    = r3.selectbox(f"Asset Class #{i+1}",
                                  ["equity", "bond", "gic", "cash", "reit", "other"],
                                  index=["equity","bond","gic","cash","reit","other"].index(
                                      pre.get("asset_class", "equity")),
                                  key=f"reb_ac_{i}")
            if sym and val > 0:
                holdings_data.append({"symbol": sym, "value": val, "asset_class": ac})

        new_contributions = st.number_input("New Contributions Available ($, optional)",
                                             min_value=0, max_value=500_000, value=0, step=500,
                                             help="If provided, buy-only guidance shows how to deploy new money to reduce drift.")
        threshold = st.number_input("Rebalance Threshold (pp)", min_value=1.0, max_value=20.0,
                                     value=5.0, step=1.0)
        submitted = st.form_submit_button("Analyse Drift", type="primary", use_container_width=True)

    if not submitted or not holdings_data:
        if not holdings_data:
            st.info("Add at least one position with a value > $0 to analyse drift.")
        return

    from agents.ori_wb.rebalancer import HoldingInput, analyse_drift
    holdings = [HoldingInput(symbol=h["symbol"], name=h["symbol"],
                              market_value=float(h["value"]), asset_class=h["asset_class"])
                for h in holdings_data]

    result = analyse_drift(
        holdings             = holdings,
        target_equities_pct  = tgt.equities_pct,
        target_bonds_pct     = tgt.bonds_pct,
        target_cash_pct      = tgt.cash_pct,
        rebalance_threshold  = float(threshold),
        new_contributions    = float(new_contributions),
    )

    st.divider()
    if result.needs_rebalance:
        st.warning(f"Rebalancing suggested — max drift: {result.max_drift_pp:.1f} pp")
    else:
        st.success(f"Portfolio is on target — max drift: {result.max_drift_pp:.1f} pp")

    # Metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Portfolio", _fmt(result.total_value))
    eq_row = next((b for b in result.buckets if b.bucket == "equities"), None)
    bd_row = next((b for b in result.buckets if b.bucket == "bonds"),    None)
    ca_row = next((b for b in result.buckets if b.bucket == "cash"),     None)
    if eq_row: m2.metric("Equities", f"{eq_row.pct:.1f}%", delta=f"{eq_row.drift_pp:+.1f} pp vs target", delta_color="off")
    if bd_row: m3.metric("Bonds / GICs", f"{bd_row.pct:.1f}%", delta=f"{bd_row.drift_pp:+.1f} pp vs target", delta_color="off")
    if ca_row: m4.metric("Cash", f"{ca_row.pct:.1f}%", delta=f"{ca_row.drift_pp:+.1f} pp vs target", delta_color="off")

    if _PLOTLY:
        # Side-by-side current vs target
        buckets_order = ["Equities", "Bonds / GICs", "Cash"]
        current_vals  = [eq_row.pct if eq_row else 0, bd_row.pct if bd_row else 0, ca_row.pct if ca_row else 0]
        target_vals   = [tgt.equities_pct, tgt.bonds_pct, tgt.cash_pct]

        fig = go.Figure()
        fig.add_trace(go.Bar(name="Current", x=buckets_order, y=current_vals,
                             marker_color="#2563EB", text=[f"{v:.1f}%" for v in current_vals], textposition="outside"))
        fig.add_trace(go.Bar(name="Target",  x=buckets_order, y=target_vals,
                             marker_color="#9CA3AF", text=[f"{v:.0f}%" for v in target_vals], textposition="outside"))
        fig.update_layout(
            barmode="group", title="Current vs Target Allocation (%)",
            yaxis_title="%", height=320, margin=dict(l=0, r=0, t=50, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Trade guidance table
    if result.trades:
        st.markdown("**Rebalancing Guidance**")
        import pandas as pd
        trade_rows = []
        for t in result.trades:
            row = {
                "Bucket":      t.bucket.capitalize(),
                "Action":      t.action,
                "Drift":       f"{t.drift_pp:+.1f} pp",
                "Full Rebalance Amount": _fmt(t.amount),
            }
            if new_contributions > 0:
                row["Buy-Only (new money)"] = _fmt(t.buy_only_amount)
            trade_rows.append(row)
        st.dataframe(pd.DataFrame(trade_rows), use_container_width=True, hide_index=True)
        st.caption("Full Rebalance: sell/buy to restore exact target. Buy-Only: direct new contributions to under-weight buckets (tax-efficient, avoids triggering capital gains).")

    if result.unclassified:
        st.warning(f"Could not classify: {', '.join(result.unclassified)}. These are excluded from drift calculation.")


def _get_portfolio_holdings() -> list[dict]:
    """Try to read holdings from Portfolio session state."""
    try:
        from core.dashboard_cache import load_summary
        summary = load_summary()
        positions = summary.get("positions_summary", [])
        price_data = st.session_state.get("price_data", {}).get("price_data", {})

        holdings = []
        for p in positions:
            sym   = str(p.get("symbol", "")).upper()
            price = (price_data.get(sym, {}).get("price") or 0)
            qty   = float(p.get("quantity") or 0)
            mv    = (price * qty) if price and qty else float(p.get("market_value") or 0)
            ac    = str(p.get("asset_class", "equity")).lower()
            if mv > 0:
                holdings.append({"symbol": sym, "value": mv, "asset_class": ac})
        return holdings
    except Exception:
        return []


# ── Tab 5: Net Worth ──────────────────────────────────────────────────────────

def _tab_net_worth(profile: dict) -> None:
    st.subheader("Net Worth Balance Sheet")
    st.caption(
        "Your complete financial picture: assets minus liabilities. "
        "Inspired by the Kubera balance-sheet approach — one view of everything you own and owe."
    )

    saved_nw = profile.get("net_worth", {})
    saved_assets = saved_nw.get("assets", [])
    saved_liab   = saved_nw.get("liabilities", [])

    # ── Assets form ───────────────────────────────────────────────────────
    st.markdown("**Assets**")
    asset_definitions = [
        # (label, category, default_value)
        ("RRSP / RRIF",           "registered",  "rrsp_rrif",    0),
        ("TFSA",                  "registered",  "tfsa",         0),
        ("Pension (commuted est.)", "registered","pension",      0),
        ("Non-Reg Investments",   "non_reg",     "non_reg",      0),
        ("Primary Residence",     "real_estate", "home",         0),
        ("Rental / Other Property","real_estate","rental",       0),
        ("Vehicles",              "vehicle",     "vehicles",     0),
        ("Other Assets",          "other",       "other_assets", 0),
    ]

    _saved_map = {a.get("key", ""): a.get("value", 0) for a in saved_assets}

    asset_cols = st.columns(2)
    asset_inputs = []
    for i, (label, cat, key, default) in enumerate(asset_definitions):
        col = asset_cols[i % 2]
        val = col.number_input(label, min_value=0, max_value=10_000_000,
                                value=int(_saved_map.get(key, default)), step=1_000,
                                key=f"nw_asset_{key}")
        asset_inputs.append({"label": label, "category": cat, "key": key, "value": val})

    # ── Liabilities form ──────────────────────────────────────────────────
    st.markdown("**Liabilities**")
    liab_definitions = [
        ("Mortgage",         "mortgage",  3.5, 0),
        ("HELOC",            "heloc",     6.5, 0),
        ("Car Loan(s)",      "car_loan",  7.0, 0),
        ("Student Loans",    "student",   5.0, 0),
        ("Personal Loan(s)", "personal",  9.0, 0),
        ("Credit Card Debt", "cc",        20.0, 0),
        ("Other Debt",       "other_debt",5.0, 0),
    ]

    _saved_liab_map = {l.get("key", ""): l for l in saved_liab}

    liab_cols = st.columns(2)
    liab_inputs = []
    for i, (label, key, default_rate, _) in enumerate(liab_definitions):
        col = liab_cols[i % 2]
        saved_l = _saved_liab_map.get(key, {})
        with col:
            lv1, lv2 = st.columns([3, 2])
            bal  = lv1.number_input(f"{label} ($)", min_value=0, max_value=5_000_000,
                                     value=int(saved_l.get("balance", 0)), step=1_000,
                                     key=f"nw_liab_{key}")
            rate = lv2.number_input(f"Rate (%)", min_value=0.0, max_value=30.0,
                                     value=float(saved_l.get("rate_pct", default_rate)), step=0.25,
                                     key=f"nw_rate_{key}")
        liab_inputs.append({"label": label, "key": key, "balance": bal, "rate_pct": rate})

    col_calc, col_save = st.columns(2)
    calc  = col_calc.button("Calculate Net Worth", type="primary", use_container_width=True)
    save  = col_save.button("Save Balance Sheet", use_container_width=True)

    if save:
        nw_data = {
            "assets":      [{"label": a["label"], "category": a["category"], "key": a["key"], "value": a["value"]} for a in asset_inputs],
            "liabilities": [{"label": l["label"], "key": l["key"], "balance": l["balance"], "rate_pct": l["rate_pct"]} for l in liab_inputs],
        }
        profile["net_worth"] = nw_data
        _save_profile(profile)
        st.success("Balance sheet saved.")

    if not calc and not save:
        return

    from agents.ori_wb.net_worth import AssetItem, LiabilityItem, NetWorthInput, compute_net_worth
    assets = [AssetItem(label=a["label"], value=float(a["value"]), category=a["category"])
              for a in asset_inputs if a["value"] > 0]
    liabilities = [LiabilityItem(label=l["label"], balance=float(l["balance"]), rate_pct=float(l["rate_pct"]))
                   for l in liab_inputs if l["balance"] > 0]

    inp    = NetWorthInput(assets=assets, liabilities=liabilities)
    result = compute_net_worth(inp)

    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Assets",      _fmt(result.total_assets))
    m2.metric("Total Liabilities", _fmt(result.total_liabilities))
    nw_delta = f"Leverage {result.leverage_ratio:.0%}"
    m3.metric("Net Worth", _fmt(result.net_worth),
              delta=nw_delta,
              delta_color="normal" if result.leverage_ratio < 0.3 else "inverse")

    if result.debt_cost_annual > 0:
        st.caption(f"Estimated annual interest cost: {_fmt(result.debt_cost_annual)}/yr")

    st.info(result.commentary)

    if _PLOTLY:
        # ── Asset breakdown donut ─────────────────────────────────────────
        if result.asset_categories:
            labels = [c.label for c in result.asset_categories]
            values = [c.total for c in result.asset_categories]
            colours = ["#2563EB", "#3B82F6", "#10B981", "#059669", "#8B5CF6", "#F59E0B"]

            fig_assets = go.Figure(go.Pie(
                labels=labels, values=values,
                hole=0.42,
                marker_colors=colours[:len(labels)],
                textinfo="label+percent",
                hovertemplate="%{label}: $%{value:,.0f}<extra></extra>",
            ))
            fig_assets.update_layout(
                title="Asset Breakdown",
                height=340, margin=dict(l=0, r=0, t=50, b=0), showlegend=False,
            )

        # ── Waterfall: assets → liabilities → net worth ───────────────────
        fig_wf = go.Figure(go.Waterfall(
            name="", orientation="v",
            measure=["absolute", "relative", "total"],
            x=["Total Assets", "Liabilities", "Net Worth"],
            y=[result.total_assets, -result.total_liabilities, 0],
            connector={"line": {"color": "#6B7280"}},
            increasing={"marker": {"color": "#059669"}},
            decreasing={"marker": {"color": "#DC2626"}},
            totals={"marker": {"color": "#2563EB"}},
            texttemplate="$%{y:,.0f}", textposition="outside",
        ))
        fig_wf.update_layout(
            title="Net Worth Waterfall",
            yaxis_tickformat="$,.0f",
            height=340, margin=dict(l=0, r=0, t=50, b=0),
        )

        ch1, ch2 = st.columns(2)
        if result.asset_categories:
            with ch1:
                st.plotly_chart(fig_assets, use_container_width=True)
        with ch2:
            st.plotly_chart(fig_wf, use_container_width=True)

    # ── Breakdown table ───────────────────────────────────────────────────
    with st.expander("Full breakdown"):
        import pandas as pd
        rows = []
        for a in result.asset_categories:
            rows.append({"Type": "Asset", "Item": a.label, "Amount": _fmt(a.total), "% of Assets": f"{a.pct_of_assets:.1f}%"})
        for l in liabilities:
            rows.append({"Type": "Liability", "Item": l.label, "Amount": _fmt(l.balance), "% of Assets": "—"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Profile form (sidebar) ────────────────────────────────────────────────────

def _profile_sidebar() -> dict:
    """Load existing profile or return empty. Sidebar quick-save for key fields."""
    profile = _load_profile()

    with st.sidebar:
        st.markdown("### Wealth Builder Profile")
        with st.expander("Quick Setup", expanded=not profile):
            fin  = profile.get("financials", {})
            pref = profile.get("preferences", {})
            age       = st.number_input("Current Age", 18, 70, int(fin.get("current_age", 35)), key="sb_age")
            ret_age   = st.number_input("Target Retirement Age", 40, 75, int(fin.get("target_retirement_age", 60)), key="sb_ret")
            income    = st.number_input("Gross Income ($)", 0, 1_000_000, int(fin.get("gross_income", 95_000)), step=1_000, key="sb_income")
            province  = st.selectbox("Province", ["BC","AB","ON","QC","SK","MB","NS","NB","PE","NL"],
                                      index=["BC","AB","ON","QC","SK","MB","NS","NB","PE","NL"].index(pref.get("province","BC")),
                                      key="sb_prov")
            risk      = st.selectbox("Risk Tolerance", ["conservative","moderate","aggressive"],
                                      index=["conservative","moderate","aggressive"].index(pref.get("risk_tolerance","moderate")),
                                      key="sb_risk")
            if st.button("Save Profile", use_container_width=True, key="sb_save"):
                profile.setdefault("financials", {}).update({
                    "current_age": int(age),
                    "target_retirement_age": int(ret_age),
                    "gross_income": float(income),
                    "years_to_retirement": int(ret_age) - int(age),
                })
                profile.setdefault("preferences", {}).update({
                    "province":       province,
                    "risk_tolerance": risk,
                })
                _save_profile(profile)
                st.success("Saved.")
                st.rerun()

    return profile


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.title("Wealth Builder")
    st.caption("Accumulation-phase planning · RRSP/TFSA strategy · FI projections · net worth")

    profile = _profile_sidebar()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "RRSP vs TFSA",
        "Savings Projector",
        "Asset Allocation",
        "Rebalancer",
        "Net Worth",
    ])

    with tab1:
        _tab_optimizer(profile)
    with tab2:
        _tab_projector(profile)
    with tab3:
        _tab_allocation(profile)
    with tab4:
        _tab_rebalancer(profile)
    with tab5:
        _tab_net_worth(profile)

    st.divider()
    st.caption(
        "Disclaimer: All figures are estimates for planning purposes only. "
        "Tax calculations use simplified marginal rates and do not account for all deductions, credits, or personal circumstances. "
        "Consult a registered financial advisor and tax professional before acting on any projection in this tool."
    )


if __name__ == "__main__":
    main()
else:
    main()
