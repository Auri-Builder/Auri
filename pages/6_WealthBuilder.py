"""
pages/6_WealthBuilder.py
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


from core._paths import PROJECT_ROOT, get_data_dir  # noqa: F401
PROFILE_PATH  = get_data_dir() / "wealth" / "wealth_profile.yaml"
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

    pref       = profile.get("preferences", {})
    fin        = profile.get("financials", {})
    has_spouse = bool(pref.get("has_spouse", False))
    sp_fin     = profile.get("spouse", {}).get("financials", {})
    sp_pref    = profile.get("spouse", {}).get("preferences", {})

    from core.shared_profile import load_shared_profile, get_account_balances_by_owner  # noqa: PLC0415
    _sp      = load_shared_profile().get("primary", {})
    _acct_by = get_account_balances_by_owner()
    _p_acct  = _acct_by.get("primary", {})
    _s_acct  = _acct_by.get("spouse", {})

    _province_def = pref.get("province") or _sp.get("province", "BC")
    _income_def   = int(fin.get("gross_income") or _sp.get("gross_income", 0))
    _yrs_def      = int(fin.get("years_to_retirement") or
                        max(1, (_sp.get("target_retirement_age", 65) - _sp.get("current_age", 35))))

    _rrsp_bal    = int(_p_acct.get("RRSP") or _p_acct.get("RRIF") or 0)
    _tfsa_bal    = int(_p_acct.get("TFSA") or 0)
    _sp_rrsp_bal = int(_s_acct.get("RRSP") or _s_acct.get("RRIF") or 0)
    _sp_tfsa_bal = int(_s_acct.get("TFSA") or 0)

    if not _acct_by:
        from core.shared_profile import get_account_balances  # noqa: PLC0415
        _all = get_account_balances()
        _rrsp_bal = int(_all.get("RRSP", 0))
        _tfsa_bal = int(_all.get("TFSA", 0))

    if _rrsp_bal or _tfsa_bal:
        st.caption(f"Portfolio CSV — Primary: RRSP ${_rrsp_bal:,.0f} · TFSA ${_tfsa_bal:,.0f} "
                   "(contribution room ≠ balance; check CRA My Account)")
    if has_spouse and (_sp_rrsp_bal or _sp_tfsa_bal):
        st.caption(f"Portfolio CSV — Spouse: RRSP ${_sp_rrsp_bal:,.0f} · TFSA ${_sp_tfsa_bal:,.0f}")

    _provinces = ["BC","AB","ON","QC","SK","MB","NS","NB","PE","NL"]

    _RAN  = "wb_opt_ran"
    _DATA = "wb_opt_data"
    _ran  = st.session_state.get(_RAN, False)

    with st.expander("⚙️ Contribution Settings", expanded=not _ran):
        with st.form("optimizer_form"):
            if has_spouse:
                st.markdown("**Primary**")
            c1, c2, c3 = st.columns(3)
            gross_income   = c1.number_input("Gross Annual Income ($)", min_value=0, max_value=1_000_000,
                                              value=_income_def, step=1_000)
            savings_amount = c2.number_input("Amount to Contribute This Year ($)", min_value=0, max_value=500_000,
                                              value=int(fin.get("annual_savings", 0)), step=500)
            province       = c3.selectbox("Province", _provinces,
                                           index=_provinces.index(_province_def) if _province_def in _provinces else 0)

            c4, c5, c6 = st.columns(3)
            rrsp_room  = c4.number_input("RRSP Room Remaining ($)", min_value=0, max_value=500_000,
                                          value=int(fin.get("rrsp_room", 0)), step=1_000,
                                          help="From your CRA My Account or most recent NOA.")
            tfsa_room  = c5.number_input("TFSA Room Remaining ($)", min_value=0, max_value=200_000,
                                          value=int(fin.get("tfsa_room", 0)), step=500)
            ret_income = c6.number_input("Expected Retirement Income ($)", min_value=0, max_value=500_000,
                                          value=int(fin.get("expected_retirement_income", 0)), step=1_000)

            c7, c8 = st.columns(2)
            yrs_to_ret  = c7.number_input("Years to Retirement", min_value=1, max_value=50,
                                           value=_yrs_def, step=1)
            growth_rate = c8.number_input("Expected Annual Return (%)", min_value=0.0, max_value=15.0,
                                           value=float(fin.get("growth_rate_pct", 6.0)), step=0.5)

            if has_spouse:
                st.divider()
                st.markdown("**Spouse**")
                _sp_prov_def = sp_pref.get("province", _province_def)
                _sp_yrs_def  = max(1, int(sp_fin.get("years_to_retirement", _yrs_def)))
                _sp_inc_def  = int(sp_fin.get("gross_income", 0))

                s1, s2, s3 = st.columns(3)
                sp_gross   = s1.number_input("Spouse Gross Income ($)", min_value=0, max_value=1_000_000,
                                              value=_sp_inc_def, step=1_000, key="opt_sp_income")
                sp_savings = s2.number_input("Spouse Contribution ($)", min_value=0, max_value=500_000,
                                              value=int(sp_fin.get("annual_savings", 0)), step=500, key="opt_sp_savings")
                sp_prov    = s3.selectbox("Spouse Province", _provinces,
                                           index=_provinces.index(_sp_prov_def) if _sp_prov_def in _provinces else 0,
                                           key="opt_sp_prov")
                s4, s5, s6 = st.columns(3)
                sp_rrsp_room = s4.number_input("Spouse RRSP Room ($)", min_value=0, max_value=500_000,
                                                value=int(sp_fin.get("rrsp_room", 0)), step=1_000, key="opt_sp_rrsp")
                sp_tfsa_room = s5.number_input("Spouse TFSA Room ($)", min_value=0, max_value=200_000,
                                                value=int(sp_fin.get("tfsa_room", 0)), step=500, key="opt_sp_tfsa")
                sp_ret_inc   = s6.number_input("Spouse Expected Retirement Income ($)", min_value=0, max_value=500_000,
                                                value=int(sp_fin.get("expected_retirement_income", 0)), step=1_000, key="opt_sp_ret_inc")
                s7, s8 = st.columns(2)
                sp_yrs    = s7.number_input("Spouse Years to Retirement", min_value=1, max_value=50,
                                             value=_sp_yrs_def, step=1, key="opt_sp_yrs")
                sp_return = s8.number_input("Spouse Expected Return (%)", min_value=0.0, max_value=15.0,
                                             value=float(sp_fin.get("growth_rate_pct", 6.0)), step=0.5, key="opt_sp_return")

            submitted = st.form_submit_button("Calculate", type="primary", use_container_width=True)

    if submitted:
        _store = {
            "has_spouse": has_spouse,
            "p": {
                "gross_income":   gross_income,
                "savings_amount": savings_amount,
                "rrsp_room":      rrsp_room,
                "tfsa_room":      tfsa_room,
                "province":       province,
                "ret_income":     ret_income,
                "yrs_to_ret":     yrs_to_ret,
                "growth_rate":    growth_rate,
            },
        }
        if has_spouse:
            _store["sp"] = {
                "sp_gross":    sp_gross,
                "sp_savings":  sp_savings,
                "sp_rrsp_room": sp_rrsp_room,
                "sp_tfsa_room": sp_tfsa_room,
                "sp_prov":     sp_prov,
                "sp_ret_inc":  sp_ret_inc,
                "sp_yrs":      sp_yrs,
                "sp_return":   sp_return,
            }
        st.session_state[_DATA] = _store
        st.session_state[_RAN]  = True
        st.rerun()

    if not _ran:
        return

    # Restore local variables from stored state
    _d          = st.session_state[_DATA]
    has_spouse  = _d["has_spouse"]
    gross_income   = _d["p"]["gross_income"]
    savings_amount = _d["p"]["savings_amount"]
    rrsp_room      = _d["p"]["rrsp_room"]
    tfsa_room      = _d["p"]["tfsa_room"]
    province       = _d["p"]["province"]
    ret_income     = _d["p"]["ret_income"]
    yrs_to_ret     = _d["p"]["yrs_to_ret"]
    growth_rate    = _d["p"]["growth_rate"]
    if has_spouse:
        sp_gross     = _d["sp"]["sp_gross"]
        sp_savings   = _d["sp"]["sp_savings"]
        sp_rrsp_room = _d["sp"]["sp_rrsp_room"]
        sp_tfsa_room = _d["sp"]["sp_tfsa_room"]
        sp_prov      = _d["sp"]["sp_prov"]
        sp_ret_inc   = _d["sp"]["sp_ret_inc"]
        sp_yrs       = _d["sp"]["sp_yrs"]
        sp_return    = _d["sp"]["sp_return"]

    from agents.ori_wb.optimizer import OptimizerInput, optimise
    inp_p = OptimizerInput(
        gross_income               = float(gross_income),
        savings_available          = float(savings_amount),
        rrsp_room_remaining        = float(rrsp_room),
        tfsa_room_remaining        = float(tfsa_room),
        province                   = province,
        current_year               = 2026,
        expected_retirement_income = float(ret_income),
        growth_rate                = float(growth_rate) / 100.0,
        years_to_retirement        = int(yrs_to_ret),
    )
    result_p = optimise(inp_p)

    st.divider()
    st.subheader("Optimisation Results")

    if has_spouse:
        inp_s = OptimizerInput(
            gross_income               = float(sp_gross),
            savings_available          = float(sp_savings),
            rrsp_room_remaining        = float(sp_rrsp_room),
            tfsa_room_remaining        = float(sp_tfsa_room),
            province                   = sp_prov,
            current_year               = 2026,
            expected_retirement_income = float(sp_ret_inc),
            growth_rate                = float(sp_return) / 100.0,
            years_to_retirement        = int(sp_yrs),
        )
        result_s = optimise(inp_s)

        pc, sc = st.columns(2)
        for col, label, res, inc, prov, yrs, gr, rrsp_b, tfsa_b in [
            (pc, "Primary", result_p, gross_income, province, yrs_to_ret, growth_rate, _rrsp_bal, _tfsa_bal),
            (sc, "Spouse",  result_s, sp_gross,     sp_prov,  sp_yrs,    sp_return,   _sp_rrsp_bal, _sp_tfsa_bal),
        ]:
            with col:
                st.markdown(f"**{label}**")
                st.caption(f"${inc:,.0f} income · {prov} · {yrs} yrs to retirement")
                m1, m2 = st.columns(2)
                m1.metric("RRSP", _fmt(res.recommended_rrsp))
                m2.metric("TFSA", _fmt(res.recommended_tfsa))
                m3, m4 = st.columns(2)
                m3.metric("Tax Saving", _fmt(res.rrsp_tax_saving))
                m4.metric("Non-Reg Overflow" if res.surplus_unregistered > 0 else "Unallocated",
                          _fmt(res.surplus_unregistered))
                st.info(res.rationale)
                g = (1 + float(gr) / 100) ** int(yrs)
                rate_ret = res.marginal_rate_retirement
                st.caption(f"Marginal rate now: {res.marginal_rate_now:.1%} → retirement: {rate_ret:.1%}")
                rrsp_fv = (rrsp_b + res.recommended_rrsp) * g * (1 - rate_ret)
                tfsa_fv = (tfsa_b + res.recommended_tfsa) * g
                f1, f2 = st.columns(2)
                f1.metric(f"RRSP FV ({yrs}y, after-tax)", _fmt(rrsp_fv))
                f2.metric(f"TFSA FV ({yrs}y, tax-free)", _fmt(tfsa_fv))

        st.divider()
        st.markdown("**Household Combined**")
        h1, h2, h3, h4 = st.columns(4)
        h1.metric("Total RRSP",       _fmt(result_p.recommended_rrsp + result_s.recommended_rrsp))
        h2.metric("Total TFSA",       _fmt(result_p.recommended_tfsa + result_s.recommended_tfsa))
        h3.metric("Total Tax Saving", _fmt(result_p.rrsp_tax_saving  + result_s.rrsp_tax_saving))
        h4.metric("Total Non-Reg",    _fmt(result_p.surplus_unregistered + result_s.surplus_unregistered))

        if _PLOTLY:
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Primary", x=["RRSP", "TFSA", "Non-Reg"],
                                  y=[result_p.recommended_rrsp, result_p.recommended_tfsa, result_p.surplus_unregistered],
                                  marker_color="#2563EB"))
            fig.add_trace(go.Bar(name="Spouse",  x=["RRSP", "TFSA", "Non-Reg"],
                                  y=[result_s.recommended_rrsp, result_s.recommended_tfsa, result_s.surplus_unregistered],
                                  marker_color="#059669"))
            fig.update_layout(
                title="Recommended Contribution Split — Primary vs Spouse",
                barmode="group", yaxis_tickformat="$,.0f",
                height=320, margin=dict(l=0, r=0, t=50, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, use_container_width=True)

    else:
        st.caption(f"Based on ${gross_income:,.0f} income · {province} · {yrs_to_ret} years to retirement")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Recommended RRSP", _fmt(result_p.recommended_rrsp))
        m2.metric("Recommended TFSA", _fmt(result_p.recommended_tfsa))
        m3.metric("Immediate Tax Saving", _fmt(result_p.rrsp_tax_saving),
                  help="Estimated refund from RRSP deduction at your marginal rate.")
        if result_p.surplus_unregistered > 0:
            m4.metric("Non-Registered Overflow", _fmt(result_p.surplus_unregistered))
        else:
            m4.metric("Unallocated", _fmt(0))

        st.info(result_p.rationale)

        r1, r2 = st.columns(2)
        with r1:
            st.markdown("**Rate Comparison**")
            rc1, rc2 = st.columns(2)
            rc1.metric("Marginal Rate Today", f"{result_p.marginal_rate_now:.1%}")
            rc2.metric("Est. Retirement Rate", f"{result_p.marginal_rate_retirement:.1%}",
                       delta=f"{result_p.marginal_rate_retirement - result_p.marginal_rate_now:+.1%}",
                       delta_color="inverse")

        with r2:
            g = (1 + float(growth_rate) / 100) ** int(yrs_to_ret)
            rate_ret = result_p.marginal_rate_retirement
            total_rrsp_fv = (_rrsp_bal + result_p.recommended_rrsp) * g * (1 - rate_ret)
            total_tfsa_fv = (_tfsa_bal + result_p.recommended_tfsa) * g
            st.markdown(f"**Estimated Future Value in {yrs_to_ret} years**")
            st.caption(f"What today's balances + this year's contributions grow to at {growth_rate}% return")
            pv1, pv2 = st.columns(2)
            pv1.metric("RRSP (after-tax at withdrawal)", _fmt(total_rrsp_fv))
            pv2.metric("TFSA (withdrawn tax-free)", _fmt(total_tfsa_fv))

        if result_p.rrsp_capped_by_room:
            st.warning(f"RRSP room is the binding constraint at {_fmt(rrsp_room)}. Consider maximising TFSA with the remainder.")
        if result_p.tfsa_capped_by_room:
            st.warning(f"TFSA room is the binding constraint at {_fmt(tfsa_room)}. Consider non-registered investing for the surplus.")

        if _PLOTLY and (result_p.recommended_rrsp > 0 or result_p.recommended_tfsa > 0):
            fig = go.Figure(go.Bar(
                x=["RRSP", "TFSA", "Non-Registered" if result_p.surplus_unregistered > 0 else None],
                y=[result_p.recommended_rrsp, result_p.recommended_tfsa,
                   result_p.surplus_unregistered if result_p.surplus_unregistered > 0 else None],
                marker_color=["#2563EB", "#059669", "#9CA3AF"],
                text=[_fmt(v) for v in [result_p.recommended_rrsp, result_p.recommended_tfsa,
                                         result_p.surplus_unregistered]],
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

    pref       = profile.get("preferences", {})
    fin        = profile.get("financials", {})
    has_spouse = bool(pref.get("has_spouse", False))
    sp_fin     = profile.get("spouse", {}).get("financials", {})

    _portfolio_mv = _get_portfolio_market_value()
    _savings_default = int(fin.get("current_savings", _portfolio_mv or 0))
    if _portfolio_mv:
        st.info(f"Current savings pre-populated from your portfolio CSV: **${_portfolio_mv:,.0f}**. "
                "Adjust if you have additional savings outside the portfolio.")

    _RAN  = "wb_proj_ran"
    _DATA = "wb_proj_data"
    _ran  = st.session_state.get(_RAN, False)

    with st.expander("⚙️ Projection Settings", expanded=not _ran):
        with st.form("projector_form"):
            if has_spouse:
                st.markdown("**Shared Parameters**")
                sh1, sh2, sh3 = st.columns(3)
                expected_return = sh1.number_input("Expected Annual Return (%)", min_value=0.0, max_value=15.0,
                                                    value=float(fin.get("growth_rate_pct", 6.0)), step=0.5)
                inflation   = sh2.number_input("Inflation (%)", min_value=0.0, max_value=10.0,
                                                value=float(fin.get("inflation_pct", 2.5)), step=0.1)
                fi_multiple = sh3.number_input("FI Multiple (×)", min_value=10.0, max_value=40.0,
                                                value=float(fin.get("fi_multiple", 25.0)), step=1.0,
                                                help="FI target = annual spending × this multiple (25 = 4% SWR).")
                st.divider()
                pc, sc = st.columns(2)
                with pc:
                    st.markdown("**Primary**")
                    current_age    = st.number_input("Current Age", min_value=18, max_value=70,
                                                      value=int(fin.get("current_age", 35)), step=1, key="proj_p_age")
                    target_ret_age = st.number_input("Target Retirement Age", min_value=40, max_value=75,
                                                      value=int(fin.get("target_retirement_age", 60)), step=1, key="proj_p_ret")
                    current_savings = st.number_input("Current Total Savings ($)", min_value=0, max_value=10_000_000,
                                                       value=_savings_default, step=5_000, key="proj_p_savings")
                    annual_income  = st.number_input("Gross Annual Income ($)", min_value=0, max_value=1_000_000,
                                                      value=int(fin.get("gross_income", 95_000)), step=1_000, key="proj_p_income")
                    savings_rate   = st.number_input("Savings Rate (% of income)", min_value=0.0, max_value=80.0,
                                                      value=float(fin.get("savings_rate_pct", 20.0)), step=1.0, key="proj_p_rate")
                    annual_spend   = st.number_input("Annual Spending ($, 0 = derive)", min_value=0, max_value=500_000,
                                                      value=0, step=1_000, key="proj_p_spend")
                with sc:
                    st.markdown("**Spouse**")
                    sp_age     = st.number_input("Spouse Age", min_value=18, max_value=70,
                                                  value=int(sp_fin.get("current_age", 35)), step=1, key="proj_s_age")
                    sp_ret_age = st.number_input("Spouse Retirement Age", min_value=40, max_value=75,
                                                  value=int(sp_fin.get("target_retirement_age", 60)), step=1, key="proj_s_ret")
                    sp_savings = st.number_input("Spouse Current Savings ($)", min_value=0, max_value=10_000_000,
                                                  value=int(sp_fin.get("current_savings", 0)), step=5_000, key="proj_s_savings")
                    sp_income  = st.number_input("Spouse Gross Income ($)", min_value=0, max_value=1_000_000,
                                                  value=int(sp_fin.get("gross_income", 0)), step=1_000, key="proj_s_income")
                    sp_rate    = st.number_input("Spouse Savings Rate (%)", min_value=0.0, max_value=80.0,
                                                  value=float(sp_fin.get("savings_rate_pct", 20.0)), step=1.0, key="proj_s_rate")
                    sp_spend   = st.number_input("Spouse Annual Spending ($, 0 = derive)", min_value=0, max_value=500_000,
                                                  value=0, step=1_000, key="proj_s_spend")
            else:
                c1, c2, c3 = st.columns(3)
                current_age    = c1.number_input("Current Age", min_value=18, max_value=70,
                                                  value=int(fin.get("current_age", 35)), step=1)
                target_ret_age = c2.number_input("Target Retirement Age", min_value=40, max_value=75,
                                                  value=int(fin.get("target_retirement_age", 60)), step=1)
                current_savings = c3.number_input("Current Total Savings ($)", min_value=0, max_value=10_000_000,
                                                   value=_savings_default, step=5_000)
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

    if submitted:
        _store = {
            "has_spouse": has_spouse,
            "p": {
                "current_age":      current_age,
                "current_savings":  current_savings,
                "annual_income":    annual_income,
                "savings_rate":     savings_rate,
                "expected_return":  expected_return,
                "inflation":        inflation,
                "target_ret_age":   target_ret_age,
                "fi_multiple":      fi_multiple,
                "annual_spend":     annual_spend,
            },
        }
        if has_spouse:
            _store["sp"] = {
                "sp_age":      sp_age,
                "sp_savings":  sp_savings,
                "sp_income":   sp_income,
                "sp_rate":     sp_rate,
                "sp_ret_age":  sp_ret_age,
                "sp_spend":    sp_spend,
            }
        st.session_state[_DATA] = _store
        st.session_state[_RAN]  = True
        st.rerun()

    if not _ran:
        return

    # Restore local variables from stored state
    _d              = st.session_state[_DATA]
    has_spouse      = _d["has_spouse"]
    current_age     = _d["p"]["current_age"]
    current_savings = _d["p"]["current_savings"]
    annual_income   = _d["p"]["annual_income"]
    savings_rate    = _d["p"]["savings_rate"]
    expected_return = _d["p"]["expected_return"]
    inflation       = _d["p"]["inflation"]
    target_ret_age  = _d["p"]["target_ret_age"]
    fi_multiple     = _d["p"]["fi_multiple"]
    annual_spend    = _d["p"]["annual_spend"]
    if has_spouse:
        sp_age     = _d["sp"]["sp_age"]
        sp_savings = _d["sp"]["sp_savings"]
        sp_income  = _d["sp"]["sp_income"]
        sp_rate    = _d["sp"]["sp_rate"]
        sp_ret_age = _d["sp"]["sp_ret_age"]
        sp_spend   = _d["sp"]["sp_spend"]

    from agents.ori_wb.projector import ProjectorInput, project

    inp_p = ProjectorInput(
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
    result_p = project(inp_p)

    st.divider()
    st.subheader("Projection Results")

    if has_spouse:
        inp_s = ProjectorInput(
            current_age           = int(sp_age),
            current_savings       = float(sp_savings),
            annual_income         = float(sp_income),
            savings_rate_pct      = float(sp_rate),
            expected_return_pct   = float(expected_return),
            inflation_pct         = float(inflation),
            target_retirement_age = int(sp_ret_age),
            fi_multiple           = float(fi_multiple),
            annual_spending       = float(sp_spend),
        )
        result_s = project(inp_s)

        pc, sc = st.columns(2)
        for col, label, res, age, ret_age in [
            (pc, "Primary", result_p, current_age, target_ret_age),
            (sc, "Spouse",  result_s, sp_age,      sp_ret_age),
        ]:
            with col:
                st.markdown(f"**{label}**")
                st.caption(f"Age {int(age)} → {int(ret_age)} · {expected_return:.1f}% return · {inflation:.1f}% inflation")
                m1, m2 = st.columns(2)
                m1.metric("Nest Egg at Target", _fmt(res.balance_at_target))
                m2.metric("FI Number at Target", _fmt(res.fi_number_at_target))
                m3, m4 = st.columns(2)
                if res.shortfall_at_target > 0:
                    m3.metric("Shortfall", _fmt(res.shortfall_at_target), delta=f"-{_fmt(res.shortfall_at_target)}", delta_color="inverse")
                else:
                    m3.metric("Surplus", _fmt(-res.shortfall_at_target), delta=f"+{_fmt(-res.shortfall_at_target)}", delta_color="normal")
                if res.fi_age:
                    m4.metric("FI Age", str(res.fi_age),
                              delta=f"{res.fi_age - int(ret_age):+d} vs target",
                              delta_color="normal" if res.fi_age <= int(ret_age) else "inverse")
                else:
                    m4.metric("FI Age", "Not reached", delta="Increase savings or return", delta_color="inverse")

        # Household chart — combined balance vs household FI number
        if _PLOTLY:
            max_age = max(max(r.age for r in result_p.rows), max(r.age for r in result_s.rows))
            min_age = min(result_p.rows[0].age, result_s.rows[0].age)
            ages = list(range(min_age, max_age + 1))

            bal_p_by_age = {r.age: r.balance for r in result_p.rows}
            bal_s_by_age = {r.age: r.balance for r in result_s.rows}
            fi_p_by_age  = {r.age: r.fi_number for r in result_p.rows}
            fi_s_by_age  = {r.age: r.fi_number for r in result_s.rows}

            combined_bal = [bal_p_by_age.get(a, 0) + bal_s_by_age.get(a, 0) for a in ages]
            combined_fi  = [fi_p_by_age.get(a, 0) + fi_s_by_age.get(a, 0) for a in ages]
            bal_p_list   = [bal_p_by_age.get(a, 0) for a in ages]
            bal_s_list   = [bal_s_by_age.get(a, 0) for a in ages]

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=ages, y=combined_bal, name="Household Balance",
                                     line=dict(color="#2563EB", width=2.5),
                                     fill="tozeroy", fillcolor="rgba(37,99,235,0.08)",
                                     hovertemplate="Age %{x}<br>Household: $%{y:,.0f}<extra></extra>"))
            fig.add_trace(go.Scatter(x=ages, y=bal_p_list, name="Primary",
                                     line=dict(color="#7C3AED", width=1.5, dash="dot"),
                                     hovertemplate="Age %{x}<br>Primary: $%{y:,.0f}<extra></extra>"))
            fig.add_trace(go.Scatter(x=ages, y=bal_s_list, name="Spouse",
                                     line=dict(color="#059669", width=1.5, dash="dot"),
                                     hovertemplate="Age %{x}<br>Spouse: $%{y:,.0f}<extra></extra>"))
            fig.add_trace(go.Scatter(x=ages, y=combined_fi, name="Household FI Number",
                                     line=dict(color="#DC2626", width=2, dash="dash"),
                                     hovertemplate="Age %{x}<br>FI Target: $%{y:,.0f}<extra></extra>"))
            fig.update_layout(
                title="Household Projected Wealth vs FI Number",
                xaxis_title="Age (Primary)", yaxis_title="Portfolio Value ($)",
                yaxis_tickformat="$,.0f", hovermode="x unified",
                height=400, margin=dict(l=0, r=0, t=60, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.markdown("**Household Combined at Respective Retirement Ages**")
        h1, h2, h3 = st.columns(3)
        h1.metric("Combined Nest Egg", _fmt(result_p.balance_at_target + result_s.balance_at_target))
        h2.metric("Combined FI Number", _fmt(result_p.fi_number_at_target + result_s.fi_number_at_target))
        hh_shortfall = (result_p.shortfall_at_target + result_s.shortfall_at_target)
        if hh_shortfall > 0:
            h3.metric("Household Shortfall", _fmt(hh_shortfall), delta=f"-{_fmt(hh_shortfall)}", delta_color="inverse")
        else:
            h3.metric("Household Surplus", _fmt(-hh_shortfall), delta=f"+{_fmt(-hh_shortfall)}", delta_color="normal")

    else:
        st.caption(f"Age {int(current_age)} → {int(target_ret_age)} · {savings_rate:.0f}% savings rate · {expected_return:.1f}% return · {inflation:.1f}% inflation")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Nest Egg at Target Age", _fmt(result_p.balance_at_target))
        m2.metric("FI Number at Target Age", _fmt(result_p.fi_number_at_target))
        if result_p.shortfall_at_target > 0:
            m3.metric("Shortfall", _fmt(result_p.shortfall_at_target), delta=f"-{_fmt(result_p.shortfall_at_target)}", delta_color="inverse")
        else:
            m3.metric("Surplus", _fmt(-result_p.shortfall_at_target), delta=f"+{_fmt(-result_p.shortfall_at_target)}", delta_color="normal")
        if result_p.fi_age:
            m4.metric("FI Age", str(result_p.fi_age),
                      delta=f"{result_p.fi_age - int(target_ret_age):+d} vs target",
                      delta_color="normal" if result_p.fi_age <= int(target_ret_age) else "inverse")
        else:
            m4.metric("FI Age", "Not reached", delta="Increase savings or return", delta_color="inverse")

        if _PLOTLY:
            ages     = [r.age     for r in result_p.rows]
            balances = [r.balance for r in result_p.rows]
            fi_nums  = [r.fi_number for r in result_p.rows]

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
            fig.add_vline(x=int(target_ret_age), line=dict(color="#6B7280", dash="dot", width=1.5),
                          annotation_text="Target retirement", annotation_position="top right",
                          annotation_font_size=11)
            if result_p.fi_age:
                fig.add_vline(x=result_p.fi_age, line=dict(color="#059669", dash="dash", width=1.5),
                              annotation_text=f"FI age {result_p.fi_age}", annotation_position="top left",
                              annotation_font_size=11, annotation_font_color="#059669")
            fig.update_layout(
                title="Projected Wealth vs FI Number",
                xaxis_title="Age", yaxis_title="Portfolio Value ($)",
                yaxis_tickformat="$,.0f", hovermode="x unified",
                height=400, margin=dict(l=0, r=0, t=60, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("**Sensitivity Analysis**")
        import pandas as pd
        rows_data = []
        for s in result_p.sensitivity:
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

    fin        = profile.get("financials", {})
    pref       = profile.get("preferences", {})
    has_spouse = bool(pref.get("has_spouse", False))
    sp_fin     = profile.get("spouse", {}).get("financials", {})
    sp_pref    = profile.get("spouse", {}).get("preferences", {})

    c1, c2, c3 = st.columns(3)
    yrs_to_ret = c1.number_input("Years to Retirement", min_value=0, max_value=50,
                                  value=int(fin.get("years_to_retirement", 20)), step=1, key="alloc_yrs")
    risk       = c2.selectbox("Risk Tolerance", ["conservative", "moderate", "aggressive"],
                               index=["conservative","moderate","aggressive"].index(
                                   pref.get("risk_tolerance", "moderate")), key="alloc_risk")
    threshold  = c3.number_input("Rebalance Threshold (pp)", min_value=1.0, max_value=20.0,
                                  value=5.0, step=1.0, key="alloc_thresh",
                                  help="Flag drift if any bucket moves more than this many pp from target.")

    from agents.ori_wb.allocation import target_allocation, all_risk_targets
    tgt = target_allocation(int(yrs_to_ret), risk)  # type: ignore[arg-type]

    if has_spouse:
        sp_yrs  = int(sp_fin.get("years_to_retirement", yrs_to_ret))
        sp_risk = sp_pref.get("risk_tolerance", risk)

        pc, sc = st.columns(2)
        with pc:
            st.markdown(f"**Primary — {risk.capitalize()} · {yrs_to_ret} yrs**")
            a1, a2, a3 = st.columns(3)
            a1.metric("Equities", f"{tgt.equities_pct:.0f}%")
            a2.metric("Bonds / GICs", f"{tgt.bonds_pct:.0f}%")
            a3.metric("Cash", f"{tgt.cash_pct:.0f}%")
        with sc:
            c4, c5 = st.columns(2)
            sp_yrs_input = c4.number_input("Spouse Years to Ret.", min_value=0, max_value=50,
                                            value=sp_yrs, step=1, key="alloc_sp_yrs")
            sp_risk_input = c5.selectbox("Spouse Risk", ["conservative", "moderate", "aggressive"],
                                          index=["conservative","moderate","aggressive"].index(sp_risk),
                                          key="alloc_sp_risk")
            tgt_s = target_allocation(int(sp_yrs_input), sp_risk_input)  # type: ignore[arg-type]
            st.markdown(f"**Spouse — {sp_risk_input.capitalize()} · {sp_yrs_input} yrs**")
            b1, b2, b3 = st.columns(3)
            b1.metric("Equities", f"{tgt_s.equities_pct:.0f}%")
            b2.metric("Bonds / GICs", f"{tgt_s.bonds_pct:.0f}%")
            b3.metric("Cash", f"{tgt_s.cash_pct:.0f}%")

        if _PLOTLY:
            ch1, ch2 = st.columns(2)
            for col, label, t in [(ch1, "Primary", tgt), (ch2, "Spouse", tgt_s)]:
                with col:
                    fig = go.Figure(go.Pie(
                        labels=["Equities", "Bonds / GICs", "Cash"],
                        values=[t.equities_pct, t.bonds_pct, t.cash_pct],
                        hole=0.45,
                        marker_colors=["#2563EB", "#7C3AED", "#059669"],
                        textinfo="label+percent",
                        hovertemplate="%{label}: %{value:.0f}%<extra></extra>",
                    ))
                    fig.update_layout(title=f"{label} Target ({t.risk.capitalize()})",
                                      height=280, margin=dict(l=0, r=0, t=50, b=0), showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)
    else:
        st.divider()
        st.markdown(f"**Target allocation — {risk.capitalize()} · {yrs_to_ret} years to retirement**")
        a1, a2, a3 = st.columns(3)
        a1.metric("Equities (Growth)",        f"{tgt.equities_pct:.0f}%")
        a2.metric("Bonds / GICs (Stability)", f"{tgt.bonds_pct:.0f}%")
        a3.metric("Cash / HISA (Liquidity)",  f"{tgt.cash_pct:.0f}%")

        if _PLOTLY:
            fig = go.Figure(go.Pie(
                labels=["Equities", "Bonds / GICs", "Cash"],
                values=[tgt.equities_pct, tgt.bonds_pct, tgt.cash_pct],
                hole=0.45,
                marker_colors=["#2563EB", "#7C3AED", "#059669"],
                textinfo="label+percent",
                hovertemplate="%{label}: %{value:.0f}%<extra></extra>",
            ))
            fig.update_layout(title=f"Target Allocation ({risk.capitalize()})",
                              height=320, margin=dict(l=0, r=0, t=50, b=0), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    with st.expander("Compare all risk levels"):
        import pandas as pd
        all_tgts = all_risk_targets(int(yrs_to_ret))
        comp = []
        for r, t in all_tgts.items():
            comp.append({
                "Risk Tolerance": r.capitalize(),
                "Equities (%)": f"{t.equities_pct:.0f}%",
                "Bonds / GICs (%)": f"{t.bonds_pct:.0f}%",
                "Cash (%)": f"{t.cash_pct:.0f}%",
            })
        st.dataframe(pd.DataFrame(comp), use_container_width=True, hide_index=True)

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

    fin        = profile.get("financials", {})
    pref       = profile.get("preferences", {})
    has_spouse = bool(pref.get("has_spouse", False))

    c1, c2 = st.columns(2)
    yrs_to_ret = c1.number_input("Years to Retirement", min_value=0, max_value=50,
                                  value=int(fin.get("years_to_retirement", 20)), step=1, key="reb_yrs")
    risk       = c2.selectbox("Risk Tolerance", ["conservative", "moderate", "aggressive"],
                               index=["conservative","moderate","aggressive"].index(
                                   pref.get("risk_tolerance", "moderate")), key="reb_risk")

    from agents.ori_wb.allocation import target_allocation
    tgt = target_allocation(int(yrs_to_ret), risk)  # type: ignore[arg-type]
    st.caption(f"Target: Equities {tgt.equities_pct:.0f}% / Bonds {tgt.bonds_pct:.0f}% / Cash {tgt.cash_pct:.0f}%")

    st.markdown("**Enter Holdings**")
    if has_spouse:
        st.caption("Pre-populated from your portfolio CSV. Set Owner to filter by household member. "
                   "Asset classes: equity, etf, bond, gic, cash, reit.")
    else:
        st.caption("Pre-populated from your loaded portfolio CSV. Adjust asset classes as needed: equity, etf, bond, gic, cash, reit.")

    _portfolio_holdings = _get_portfolio_holdings()
    n_positions = st.number_input("Number of positions", min_value=1, max_value=20,
                                   value=min(20, max(3, len(_portfolio_holdings))), step=1)

    _owner_opts = ["Primary", "Spouse", "Joint"] if has_spouse else ["Primary"]

    _RAN  = "wb_reb_ran"
    _DATA = "wb_reb_data"
    _ran  = st.session_state.get(_RAN, False)

    holdings_data = []

    with st.expander("⚙️ Rebalancer Inputs", expanded=not _ran):
        with st.form("rebalancer_form"):
            for i in range(int(n_positions)):
                pre = _portfolio_holdings[i] if i < len(_portfolio_holdings) else {}
                if has_spouse:
                    r1, r2, r3, r4 = st.columns([2, 2, 1, 1])
                else:
                    r1, r2, r3 = st.columns([2, 2, 1])
                sym = r1.text_input(f"Symbol / Name #{i+1}", value=pre.get("symbol", ""), key=f"reb_sym_{i}")
                val = r2.number_input(f"Market Value ($) #{i+1}", min_value=0, max_value=5_000_000,
                                       value=int(pre.get("value", 0)), step=100, key=f"reb_val_{i}")
                _ac_opts = ["equity", "etf", "bond", "gic", "cash", "reit", "other"]
                _ac_val  = pre.get("asset_class", "equity")
                _ac_idx  = _ac_opts.index(_ac_val) if _ac_val in _ac_opts else 0
                ac = r3.selectbox(f"Asset Class #{i+1}", _ac_opts, index=_ac_idx, key=f"reb_ac_{i}")
                if has_spouse:
                    owner = r4.selectbox(f"Owner #{i+1}", _owner_opts, index=2, key=f"reb_owner_{i}")
                else:
                    owner = "Primary"
                if sym and val > 0:
                    holdings_data.append({"symbol": sym, "value": val, "asset_class": ac, "owner": owner})

            new_contributions = st.number_input("New Contributions Available ($, optional)",
                                                 min_value=0, max_value=500_000, value=0, step=500,
                                                 help="Deploy new money to reduce drift (buy-only guidance).")
            threshold = st.number_input("Rebalance Threshold (pp)", min_value=1.0, max_value=20.0,
                                         value=5.0, step=1.0)
            submitted = st.form_submit_button("Analyse Drift", type="primary", use_container_width=True)

    if submitted:
        if not holdings_data:
            st.info("Add at least one position with a value > $0 to analyse drift.")
        else:
            st.session_state[_DATA] = {
                "has_spouse":       has_spouse,
                "holdings_data":    holdings_data,
                "new_contributions": new_contributions,
                "threshold":        threshold,
                "tgt": {
                    "equities_pct": tgt.equities_pct,
                    "bonds_pct":    tgt.bonds_pct,
                    "cash_pct":     tgt.cash_pct,
                },
            }
            st.session_state[_RAN] = True
            st.rerun()

    if not _ran:
        if not holdings_data:
            st.info("Add at least one position with a value > $0 to analyse drift.")
        return

    # Restore local variables from stored state
    _d                = st.session_state[_DATA]
    has_spouse        = _d["has_spouse"]
    holdings_data     = _d["holdings_data"]
    new_contributions = _d["new_contributions"]
    threshold         = _d["threshold"]
    _tgt_d            = _d["tgt"]

    from agents.ori_wb.rebalancer import HoldingInput, analyse_drift

    def _run_drift(hdgs, new_cash):
        h = [HoldingInput(symbol=d["symbol"], name=d["symbol"],
                          market_value=float(d["value"]), asset_class=d["asset_class"])
             for d in hdgs]
        return analyse_drift(
            holdings            = h,
            target_equities_pct = _tgt_d["equities_pct"],
            target_bonds_pct    = _tgt_d["bonds_pct"],
            target_cash_pct     = _tgt_d["cash_pct"],
            rebalance_threshold = float(threshold),
            new_contributions   = float(new_cash),
        )

    def _show_drift(result, label: str = ""):
        if label:
            st.markdown(f"**{label}**")
        if result.needs_rebalance:
            st.warning(f"Rebalancing suggested — max drift: {result.max_drift_pp:.1f} pp")
        else:
            st.success(f"On target — max drift: {result.max_drift_pp:.1f} pp")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Portfolio", _fmt(result.total_value))
        eq_row = next((b for b in result.buckets if b.bucket == "equities"), None)
        bd_row = next((b for b in result.buckets if b.bucket == "bonds"),    None)
        ca_row = next((b for b in result.buckets if b.bucket == "cash"),     None)
        if eq_row: m2.metric("Equities", f"{eq_row.pct:.1f}%", delta=f"{eq_row.drift_pp:+.1f} pp vs target", delta_color="off")
        if bd_row: m3.metric("Bonds / GICs", f"{bd_row.pct:.1f}%", delta=f"{bd_row.drift_pp:+.1f} pp vs target", delta_color="off")
        if ca_row: m4.metric("Cash", f"{ca_row.pct:.1f}%", delta=f"{ca_row.drift_pp:+.1f} pp vs target", delta_color="off")
        if result.trades:
            import pandas as pd
            trade_rows = []
            for t in result.trades:
                row = {"Bucket": t.bucket.capitalize(), "Action": t.action, "Drift": f"{t.drift_pp:+.1f} pp",
                       "Full Rebalance": _fmt(t.amount)}
                if new_contributions > 0:
                    row["Buy-Only"] = _fmt(t.buy_only_amount)
                trade_rows.append(row)
            st.dataframe(pd.DataFrame(trade_rows), use_container_width=True, hide_index=True)
        if result.unclassified:
            st.warning(f"Unclassified: {', '.join(result.unclassified)} — excluded from drift.")

    st.divider()

    if has_spouse:
        p_hdgs = [h for h in holdings_data if h["owner"] == "Primary"]
        s_hdgs = [h for h in holdings_data if h["owner"] == "Spouse"]
        j_hdgs = [h for h in holdings_data if h["owner"] == "Joint"]

        # Household (all)
        result_all = _run_drift(holdings_data, new_contributions)

        if _PLOTLY:
            buckets_order = ["Equities", "Bonds / GICs", "Cash"]
            eq_r = next((b for b in result_all.buckets if b.bucket == "equities"), None)
            bd_r = next((b for b in result_all.buckets if b.bucket == "bonds"),    None)
            ca_r = next((b for b in result_all.buckets if b.bucket == "cash"),     None)
            current_vals = [eq_r.pct if eq_r else 0, bd_r.pct if bd_r else 0, ca_r.pct if ca_r else 0]
            target_vals  = [tgt.equities_pct, tgt.bonds_pct, tgt.cash_pct]
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Current", x=buckets_order, y=current_vals,
                                  marker_color="#2563EB", text=[f"{v:.1f}%" for v in current_vals], textposition="outside"))
            fig.add_trace(go.Bar(name="Target",  x=buckets_order, y=target_vals,
                                  marker_color="#9CA3AF", text=[f"{v:.0f}%" for v in target_vals], textposition="outside"))
            fig.update_layout(barmode="group", title="Household: Current vs Target (%)",
                              yaxis_title="%", height=300, margin=dict(l=0, r=0, t=50, b=0),
                              legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig, use_container_width=True)

        _show_drift(result_all, "Household (All Holdings)")
        st.divider()

        pc, sc = st.columns(2)
        all_p = p_hdgs + [{"symbol": h["symbol"], "value": h["value"]/2, "asset_class": h["asset_class"]} for h in j_hdgs]
        all_s = s_hdgs + [{"symbol": h["symbol"], "value": h["value"]/2, "asset_class": h["asset_class"]} for h in j_hdgs]
        with pc:
            if all_p:
                r_p = _run_drift(all_p, new_contributions / 2)
                _show_drift(r_p, "Primary (incl. 50% of joint)")
            else:
                st.info("No Primary holdings entered.")
        with sc:
            if all_s:
                r_s = _run_drift(all_s, new_contributions / 2)
                _show_drift(r_s, "Spouse (incl. 50% of joint)")
            else:
                st.info("No Spouse holdings entered.")
        st.caption("Joint holdings split 50/50 between Primary and Spouse for individual drift analysis.")

    else:
        result = _run_drift(holdings_data, new_contributions)

        if _PLOTLY:
            buckets_order = ["Equities", "Bonds / GICs", "Cash"]
            eq_row = next((b for b in result.buckets if b.bucket == "equities"), None)
            bd_row = next((b for b in result.buckets if b.bucket == "bonds"),    None)
            ca_row = next((b for b in result.buckets if b.bucket == "cash"),     None)
            current_vals = [eq_row.pct if eq_row else 0, bd_row.pct if bd_row else 0, ca_row.pct if ca_row else 0]
            target_vals  = [tgt.equities_pct, tgt.bonds_pct, tgt.cash_pct]
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Current", x=buckets_order, y=current_vals,
                                  marker_color="#2563EB", text=[f"{v:.1f}%" for v in current_vals], textposition="outside"))
            fig.add_trace(go.Bar(name="Target",  x=buckets_order, y=target_vals,
                                  marker_color="#9CA3AF", text=[f"{v:.0f}%" for v in target_vals], textposition="outside"))
            fig.update_layout(barmode="group", title="Current vs Target Allocation (%)",
                              yaxis_title="%", height=320, margin=dict(l=0, r=0, t=50, b=0),
                              legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig, use_container_width=True)

        _show_drift(result)

    st.caption("Full Rebalance: sell/buy to restore exact target. Buy-Only: direct new contributions to under-weight buckets (avoids triggering capital gains).")


def _get_portfolio_market_value() -> float:
    """Return total portfolio market value from loaded CSV + live prices. 0 if not loaded."""
    try:
        from core.dashboard_cache import load_summary
        summary    = load_summary()
        positions  = summary.get("positions_summary", [])
        price_data = st.session_state.get("price_data", {}).get("price_data", {})
        total = 0.0
        for p in positions:
            sym   = str(p.get("symbol", "")).upper()
            price = (price_data.get(sym, {}).get("price") or 0)
            qty   = float(p.get("quantity") or 0)
            mv    = (price * qty) if price and qty else float(p.get("market_value") or 0)
            total += mv
        return round(total, 0) if total > 0 else 0.0
    except Exception:
        return 0.0


_AC_NORMALISE = {
    "equity":       "equity",
    "equities":     "equity",
    "stock":        "equity",
    "etf":          "etf",
    "reit":         "reit",
    "trust":        "reit",    # income trusts → treat as equity-like
    "lp":           "reit",    # limited partnerships → equity-like
    "bond":         "bond",
    "bonds":        "bond",
    "fixed income": "bond",
    "gic":          "gic",
    "gics":         "gic",
    "preferred":    "bond",
    "mutual fund":  "bond",    # most in our portfolio are fixed income funds
    "money market": "cash",
    "cash":         "cash",
    "savings":      "cash",
    "unknown":      "equity",  # default assumption
}


def _get_portfolio_holdings() -> list[dict]:
    """Read holdings from the cached portfolio summary (loaded from CSV)."""
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
            raw_ac = str(p.get("asset_class", "equity")).lower().strip()
            ac = _AC_NORMALISE.get(raw_ac, "equity")
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

    pref       = profile.get("preferences", {})
    has_spouse = bool(pref.get("has_spouse", False))
    saved_nw   = profile.get("net_worth", {})

    from core.shared_profile import get_account_balances_by_owner, get_account_balances, non_registered_balance  # noqa: PLC0415
    _acct_by = get_account_balances_by_owner()
    _p_acct  = _acct_by.get("primary", {})
    _s_acct  = _acct_by.get("spouse",  {})

    if _acct_by:
        _csv_rrsp     = int(_p_acct.get("RRSP", 0) + _p_acct.get("RRIF", 0) + _p_acct.get("LIRA", 0))
        _csv_tfsa     = int(_p_acct.get("TFSA", 0))
        _csv_sp_rrsp  = int(_s_acct.get("RRSP", 0) + _s_acct.get("RRIF", 0) + _s_acct.get("LIRA", 0))
        _csv_sp_tfsa  = int(_s_acct.get("TFSA", 0))
        _csv_non_reg  = int(non_registered_balance())
    else:
        _acct_all    = get_account_balances()
        _csv_rrsp    = int(_acct_all.get("RRSP", 0) + _acct_all.get("RRIF", 0) + _acct_all.get("LIRA", 0))
        _csv_tfsa    = int(_acct_all.get("TFSA", 0))
        _csv_sp_rrsp = 0
        _csv_sp_tfsa = 0
        _csv_non_reg = int(non_registered_balance())

    if _csv_rrsp or _csv_tfsa or _csv_non_reg:
        st.info("Registered accounts pre-filled from your portfolio CSV. Add real estate, vehicles, and debts below.")

    saved_p  = saved_nw.get("primary",  {})
    saved_s  = saved_nw.get("spouse",   {})
    saved_j  = saved_nw.get("joint",    {})
    saved_la = saved_nw.get("liabilities", [])
    # Backward compat: legacy flat net_worth format
    if "assets" in saved_nw and not saved_p:
        _legacy_map = {a.get("key", ""): a.get("value", 0) for a in saved_nw.get("assets", [])}
        saved_p = _legacy_map

    def _nw_asset_input(label, key, default, col, prefix=""):
        widget_key = f"nw_{prefix}{key}"
        saved_val = saved_p.get(key, default) if prefix == "" else (saved_s.get(key, default) if prefix == "sp_" else saved_j.get(key, default))
        return col.number_input(label, min_value=0, max_value=10_000_000,
                                value=int(saved_val), step=1_000, key=widget_key)

    from agents.ori_wb.net_worth import AssetItem, LiabilityItem, NetWorthInput, compute_net_worth

    _NW_RAN = "wb_nw_ran"
    _nw_ran = st.session_state.get(_NW_RAN, False)

    with st.expander("⚙️ Balance Sheet Inputs", expanded=not _nw_ran):
        with st.form("nw_form"):
            # ── Assets ─────────────────────────────────────────────────────
            if has_spouse:
                pc, sc = st.columns(2)
                with pc:
                    st.markdown("**Primary Assets**")
                    p_rrsp    = st.number_input("RRSP / RRIF",           min_value=0, max_value=10_000_000, value=int(saved_p.get("rrsp_rrif",  _csv_rrsp)),    step=1_000)
                    p_tfsa    = st.number_input("TFSA",                   min_value=0, max_value=10_000_000, value=int(saved_p.get("tfsa",       _csv_tfsa)),     step=1_000)
                    p_pension = st.number_input("Pension (commuted est.)", min_value=0, max_value=10_000_000, value=int(saved_p.get("pension",    0)),             step=1_000)
                    p_nonreg  = st.number_input("Non-Reg Investments",    min_value=0, max_value=10_000_000, value=int(saved_p.get("non_reg",    _csv_non_reg)),  step=1_000)
                    p_vehicle = st.number_input("Vehicles",               min_value=0, max_value=2_000_000,  value=int(saved_p.get("vehicles",   0)),             step=1_000)
                with sc:
                    st.markdown("**Spouse Assets**")
                    s_rrsp    = st.number_input("Spouse RRSP / RRIF",     min_value=0, max_value=10_000_000, value=int(saved_s.get("rrsp_rrif",  _csv_sp_rrsp)), step=1_000)
                    s_tfsa    = st.number_input("Spouse TFSA",            min_value=0, max_value=10_000_000, value=int(saved_s.get("tfsa",       _csv_sp_tfsa)), step=1_000)
                    s_pension = st.number_input("Spouse Pension",         min_value=0, max_value=10_000_000, value=int(saved_s.get("pension",    0)),            step=1_000)
                    s_nonreg  = st.number_input("Spouse Non-Reg",         min_value=0, max_value=10_000_000, value=int(saved_s.get("non_reg",    0)),            step=1_000)
                    s_vehicle = st.number_input("Spouse Vehicles",        min_value=0, max_value=2_000_000,  value=int(saved_s.get("vehicles",   0)),            step=1_000)

                st.markdown("**Joint / Shared Assets**")
                j1, j2, j3 = st.columns(3)
                j_home   = j1.number_input("Primary Residence",        min_value=0, max_value=10_000_000, value=int(saved_j.get("home",        0)), step=1_000)
                j_rental = j2.number_input("Rental / Other Property",  min_value=0, max_value=10_000_000, value=int(saved_j.get("rental",      0)), step=1_000)
                j_other  = j3.number_input("Other Shared Assets",      min_value=0, max_value=5_000_000,  value=int(saved_j.get("other_assets", 0)), step=1_000)

            else:
                st.markdown("**Assets**")
                _saved_map = saved_p if saved_p else {a.get("key", ""): a.get("value", 0) for a in saved_nw.get("assets", [])}
                asset_definitions = [
                    ("RRSP / RRIF",             "registered",  "rrsp_rrif",    _csv_rrsp),
                    ("TFSA",                    "registered",  "tfsa",         _csv_tfsa),
                    ("Pension (commuted est.)",  "registered",  "pension",      0),
                    ("Non-Reg Investments",     "non_reg",     "non_reg",      _csv_non_reg),
                    ("Primary Residence",       "real_estate", "home",         0),
                    ("Rental / Other Property", "real_estate", "rental",       0),
                    ("Vehicles",                "vehicle",     "vehicles",     0),
                    ("Other Assets",            "other",       "other_assets", 0),
                ]
                asset_cols = st.columns(2)
                asset_inputs = []
                for i, (label, cat, key, csv_default) in enumerate(asset_definitions):
                    col = asset_cols[i % 2]
                    val = col.number_input(label, min_value=0, max_value=10_000_000,
                                           value=int(_saved_map.get(key, csv_default)), step=1_000)
                    asset_inputs.append({"label": label, "category": cat, "key": key, "value": val})

            # ── Liabilities ────────────────────────────────────────────────
            st.markdown("**Liabilities**")
            liab_definitions = [
                ("Mortgage",         "mortgage",   3.5),
                ("HELOC",            "heloc",      6.5),
                ("Car Loan(s)",      "car_loan",   7.0),
                ("Student Loans",    "student",    5.0),
                ("Personal Loan(s)", "personal",   9.0),
                ("Credit Card Debt", "cc",        20.0),
                ("Other Debt",       "other_debt", 5.0),
            ]
            _saved_liab_map = {l.get("key", ""): l for l in saved_la}
            liab_cols = st.columns(2)
            liab_inputs = []
            for i, (label, key, default_rate) in enumerate(liab_definitions):
                col = liab_cols[i % 2]
                saved_l = _saved_liab_map.get(key, {})
                with col:
                    lv1, lv2 = st.columns([3, 2])
                    bal  = lv1.number_input(f"{label} ($)", min_value=0, max_value=5_000_000,
                                             value=int(saved_l.get("balance", 0)), step=1_000,
                                             key=f"nw_liab_{key}_bal")
                    rate = lv2.number_input("Rate (%)", min_value=0.0, max_value=30.0,
                                             value=float(saved_l.get("rate_pct", default_rate)), step=0.25,
                                             key=f"nw_liab_{key}_rate")
                liab_inputs.append({"label": label, "key": key, "balance": bal, "rate_pct": rate})

            col_calc, col_save = st.columns(2)
            calc = col_calc.form_submit_button("Calculate Net Worth", type="primary", use_container_width=True)
            save = col_save.form_submit_button("Save Balance Sheet", use_container_width=True)

    if save:
        if has_spouse:
            nw_data = {
                "primary": {"rrsp_rrif": p_rrsp, "tfsa": p_tfsa, "pension": p_pension, "non_reg": p_nonreg, "vehicles": p_vehicle},
                "spouse":  {"rrsp_rrif": s_rrsp, "tfsa": s_tfsa, "pension": s_pension, "non_reg": s_nonreg, "vehicles": s_vehicle},
                "joint":   {"home": j_home, "rental": j_rental, "other_assets": j_other},
                "liabilities": [{"label": l["label"], "key": l["key"], "balance": l["balance"], "rate_pct": l["rate_pct"]} for l in liab_inputs],
            }
        else:
            nw_data = {
                "assets":      [{"label": a["label"], "category": a["category"], "key": a["key"], "value": a["value"]} for a in asset_inputs],
                "liabilities": [{"label": l["label"], "key": l["key"], "balance": l["balance"], "rate_pct": l["rate_pct"]} for l in liab_inputs],
            }
        profile["net_worth"] = nw_data
        _save_profile(profile)
        st.session_state["nw_just_saved"] = True
        st.session_state[_NW_RAN] = True
        st.rerun()

    if calc:
        st.session_state[_NW_RAN] = True
        st.rerun()

    if not _nw_ran:
        return

    if st.session_state.pop("nw_just_saved", False):
        st.success("Balance sheet saved.")

    # ── Compute net worth ──────────────────────────────────────────────────
    liabilities = [LiabilityItem(label=l["label"], balance=float(l["balance"]), rate_pct=float(l["rate_pct"]))
                   for l in liab_inputs if l["balance"] > 0]
    total_liab = sum(l["balance"] for l in liab_inputs)

    if has_spouse:
        p_assets = [
            AssetItem(label="RRSP / RRIF",    value=float(p_rrsp),    category="registered"),
            AssetItem(label="TFSA",            value=float(p_tfsa),    category="registered"),
            AssetItem(label="Pension",         value=float(p_pension), category="registered"),
            AssetItem(label="Non-Reg",         value=float(p_nonreg),  category="non_reg"),
            AssetItem(label="Vehicles",        value=float(p_vehicle), category="vehicle"),
        ]
        s_assets = [
            AssetItem(label="Spouse RRSP/RRIF", value=float(s_rrsp),    category="registered"),
            AssetItem(label="Spouse TFSA",       value=float(s_tfsa),    category="registered"),
            AssetItem(label="Spouse Pension",    value=float(s_pension), category="registered"),
            AssetItem(label="Spouse Non-Reg",    value=float(s_nonreg),  category="non_reg"),
            AssetItem(label="Spouse Vehicles",   value=float(s_vehicle), category="vehicle"),
        ]
        j_assets = [
            AssetItem(label="Primary Residence",       value=float(j_home),   category="real_estate"),
            AssetItem(label="Rental / Other Property", value=float(j_rental), category="real_estate"),
            AssetItem(label="Other Assets",            value=float(j_other),  category="other"),
        ]
        all_assets = [a for a in p_assets + s_assets + j_assets if a.value > 0]
        p_asset_list = [a for a in p_assets if a.value > 0]
        s_asset_list = [a for a in s_assets if a.value > 0]

        result_p = compute_net_worth(NetWorthInput(assets=p_asset_list, liabilities=[]))
        result_s = compute_net_worth(NetWorthInput(assets=s_asset_list, liabilities=[]))
        result_h = compute_net_worth(NetWorthInput(assets=all_assets,   liabilities=liabilities))

        st.divider()
        st.markdown("**Individual Net Worth** (assets only — shared liabilities below)")
        pc, sc, hc = st.columns(3)
        pc.metric("Primary Assets", _fmt(result_p.total_assets))
        sc.metric("Spouse Assets",  _fmt(result_s.total_assets))
        hc.metric("Joint Assets",   _fmt(float(j_home) + float(j_rental) + float(j_other)))

        st.markdown("**Household Net Worth**")
        h1, h2, h3 = st.columns(3)
        h1.metric("Total Assets",      _fmt(result_h.total_assets))
        h2.metric("Total Liabilities", _fmt(result_h.total_liabilities))
        nw_delta = f"Leverage {result_h.leverage_ratio:.0%}"
        h3.metric("Net Worth", _fmt(result_h.net_worth),
                  delta=nw_delta,
                  delta_color="normal" if result_h.leverage_ratio < 0.3 else "inverse")

        if result_h.debt_cost_annual > 0:
            st.caption(f"Estimated annual interest cost: {_fmt(result_h.debt_cost_annual)}/yr")

        st.info(result_h.commentary)

        if _PLOTLY:
            ch1, ch2 = st.columns(2)
            with ch1:
                # Side-by-side primary vs spouse assets
                fig_cmp = go.Figure()
                p_val = result_p.total_assets
                s_val = result_s.total_assets
                j_val = float(j_home) + float(j_rental) + float(j_other)
                fig_cmp.add_trace(go.Bar(
                    x=["Primary", "Spouse", "Joint"],
                    y=[p_val, s_val, j_val],
                    marker_color=["#2563EB", "#059669", "#7C3AED"],
                    text=[_fmt(v) for v in [p_val, s_val, j_val]],
                    textposition="outside",
                ))
                fig_cmp.update_layout(title="Assets by Household Member", yaxis_tickformat="$,.0f",
                                      height=320, margin=dict(l=0, r=0, t=50, b=0), showlegend=False)
                st.plotly_chart(fig_cmp, use_container_width=True)
            with ch2:
                fig_wf = go.Figure(go.Waterfall(
                    name="", orientation="v",
                    measure=["absolute", "relative", "total"],
                    x=["Total Assets", "Liabilities", "Net Worth"],
                    y=[result_h.total_assets, -result_h.total_liabilities, 0],
                    connector={"line": {"color": "#6B7280"}},
                    increasing={"marker": {"color": "#059669"}},
                    decreasing={"marker": {"color": "#DC2626"}},
                    totals={"marker":    {"color": "#2563EB"}},
                    texttemplate="$%{y:,.0f}", textposition="outside",
                ))
                fig_wf.update_layout(title="Household Net Worth Waterfall", yaxis_tickformat="$,.0f",
                                     height=320, margin=dict(l=0, r=0, t=50, b=0))
                st.plotly_chart(fig_wf, use_container_width=True)

        with st.expander("Full breakdown"):
            import pandas as pd
            rows = []
            for a in result_h.asset_categories:
                rows.append({"Type": "Asset", "Item": a.label, "Amount": _fmt(a.total), "% of Assets": f"{a.pct_of_assets:.1f}%"})
            for li in liabilities:
                rows.append({"Type": "Liability", "Item": li.label, "Amount": _fmt(li.balance), "% of Assets": "—"})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    else:
        assets = [AssetItem(label=a["label"], value=float(a["value"]), category=a["category"])
                  for a in asset_inputs if a["value"] > 0]

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
            if result.asset_categories:
                labels  = [c.label for c in result.asset_categories]
                values  = [c.total for c in result.asset_categories]
                colours = ["#2563EB", "#3B82F6", "#10B981", "#059669", "#8B5CF6", "#F59E0B"]
                fig_assets = go.Figure(go.Pie(
                    labels=labels, values=values, hole=0.42,
                    marker_colors=colours[:len(labels)], textinfo="label+percent",
                    hovertemplate="%{label}: $%{value:,.0f}<extra></extra>",
                ))
                fig_assets.update_layout(title="Asset Breakdown", height=340,
                                         margin=dict(l=0, r=0, t=50, b=0), showlegend=False)

            fig_wf = go.Figure(go.Waterfall(
                name="", orientation="v",
                measure=["absolute", "relative", "total"],
                x=["Total Assets", "Liabilities", "Net Worth"],
                y=[result.total_assets, -result.total_liabilities, 0],
                connector={"line": {"color": "#6B7280"}},
                increasing={"marker": {"color": "#059669"}},
                decreasing={"marker": {"color": "#DC2626"}},
                totals={"marker":    {"color": "#2563EB"}},
                texttemplate="$%{y:,.0f}", textposition="outside",
            ))
            fig_wf.update_layout(title="Net Worth Waterfall", yaxis_tickformat="$,.0f",
                                  height=340, margin=dict(l=0, r=0, t=50, b=0))

            ch1, ch2 = st.columns(2)
            if result.asset_categories:
                with ch1:
                    st.plotly_chart(fig_assets, use_container_width=True)
            with ch2:
                st.plotly_chart(fig_wf, use_container_width=True)

        with st.expander("Full breakdown"):
            import pandas as pd
            rows = []
            for a in result.asset_categories:
                rows.append({"Type": "Asset", "Item": a.label, "Amount": _fmt(a.total), "% of Assets": f"{a.pct_of_assets:.1f}%"})
            for li in liabilities:
                rows.append({"Type": "Liability", "Item": li.label, "Amount": _fmt(li.balance), "% of Assets": "—"})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Profile form (sidebar) ────────────────────────────────────────────────────

def _profile_sidebar() -> dict:
    """
    Load WB local profile, seeding defaults from shared_profile if available.
    Sidebar quick-save persists to both WB profile and shared_profile.
    """
    from core.shared_profile import load_shared_profile, save_shared_profile, get_account_balances_by_owner  # noqa: PLC0415

    profile  = _load_profile()
    shared   = load_shared_profile()
    sp       = shared.get("primary", {})

    fin      = profile.get("financials",  {})
    pref     = profile.get("preferences", {})
    sp_saved = profile.get("spouse",      {})
    sp_fin   = sp_saved.get("financials",  {})
    sp_pref  = sp_saved.get("preferences", {})

    _age_default      = int(fin.get("current_age")           or sp.get("current_age",      35))
    _ret_default      = int(fin.get("target_retirement_age") or sp.get("target_retirement_age", 60))
    _income_default   = int(fin.get("gross_income")          or sp.get("gross_income",     95_000))
    _province_default = pref.get("province")                  or sp.get("province",         "BC")
    _risk_default     = pref.get("risk_tolerance")            or sp.get("risk_tolerance",   "moderate")

    _acct_by_owner   = get_account_balances_by_owner()
    _sp_age_default  = int(sp_fin.get("current_age",           62))
    _sp_ret_default  = int(sp_fin.get("target_retirement_age", 65))
    _sp_inc_default  = int(sp_fin.get("gross_income",           0))
    _sp_prov_default = sp_pref.get("province",       _province_default)
    _sp_risk_default = sp_pref.get("risk_tolerance", "moderate")

    _provinces = ["BC","AB","ON","QC","SK","MB","NS","NB","PE","NL"]
    _risks     = ["conservative","moderate","aggressive"]

    with st.sidebar:
        st.markdown("### Wealth Builder")
        if sp:
            st.caption(f"Profile: {sp.get('name', 'Primary')} · age {sp.get('current_age', '?')}")
            st.page_link("pages/wizard.py", label="Edit profile in Wizard →")
        with st.expander("Quick Setup", expanded=not profile and not sp):
            _has_spouse_default = bool(pref.get("has_spouse", sp.get("has_spouse", False)))
            age      = st.number_input("Current Age", 18, 70, _age_default, key="sb_age")
            ret_age  = st.number_input("Target Retirement Age", 40, 75, _ret_default, key="sb_ret")
            income   = st.number_input("Gross Income ($)", 0, 1_000_000, _income_default, step=1_000, key="sb_income")
            province = st.selectbox("Province", _provinces,
                                     index=_provinces.index(_province_default) if _province_default in _provinces else 0,
                                     key="sb_prov")
            risk     = st.selectbox("Risk Tolerance", _risks,
                                     index=_risks.index(_risk_default) if _risk_default in _risks else 1,
                                     key="sb_risk")
            has_spouse = st.checkbox("Has spouse / partner", value=_has_spouse_default, key="sb_spouse")

            if has_spouse:
                st.caption("**Spouse**")
                sp_age     = st.number_input("Spouse Age", 18, 70, _sp_age_default, key="sb_sp_age")
                sp_ret_age = st.number_input("Spouse Retirement Age", 40, 75, _sp_ret_default, key="sb_sp_ret")
                sp_income  = st.number_input("Spouse Income ($)", 0, 1_000_000, _sp_inc_default, step=1_000, key="sb_sp_income")
                sp_prov    = st.selectbox("Spouse Province", _provinces,
                                           index=_provinces.index(_sp_prov_default) if _sp_prov_default in _provinces else 0,
                                           key="sb_sp_prov")
                sp_risk    = st.selectbox("Spouse Risk Tolerance", _risks,
                                           index=_risks.index(_sp_risk_default) if _sp_risk_default in _risks else 1,
                                           key="sb_sp_risk")

            if st.button("Save", use_container_width=True, key="sb_save"):
                profile.setdefault("financials", {}).update({
                    "current_age":           int(age),
                    "target_retirement_age": int(ret_age),
                    "gross_income":          float(income),
                    "years_to_retirement":   int(ret_age) - int(age),
                })
                profile.setdefault("preferences", {}).update({
                    "province":       province,
                    "risk_tolerance": risk,
                    "has_spouse":     has_spouse,
                })
                if has_spouse:
                    profile.setdefault("spouse", {}).setdefault("financials", {}).update({
                        "current_age":           int(sp_age),
                        "target_retirement_age": int(sp_ret_age),
                        "gross_income":          float(sp_income),
                        "years_to_retirement":   int(sp_ret_age) - int(sp_age),
                    })
                    profile["spouse"].setdefault("preferences", {}).update({
                        "province":       sp_prov,
                        "risk_tolerance": sp_risk,
                    })
                else:
                    profile.pop("spouse", None)
                _save_profile(profile)
                shared.setdefault("primary", {}).update({
                    "current_age":           int(age),
                    "gross_income":          float(income),
                    "province":              province,
                    "risk_tolerance":        risk,
                    "target_retirement_age": int(ret_age),
                    "has_spouse":            has_spouse,
                })
                save_shared_profile(shared)
                st.success("Saved.")
                st.rerun()

        # Account balances from CSV — by owner when available
        from core.shared_profile import get_account_balances  # noqa: PLC0415
        _acct = get_account_balances()
        if _acct_by_owner:
            st.divider()
            st.caption("**From your portfolio CSV:**")
            for owner, accts in _acct_by_owner.items():
                st.caption(f"*{owner.capitalize()}*")
                for acct_type, bal in accts.items():
                    st.caption(f"  {acct_type}: ${bal:,.0f}")
        elif _acct:
            st.divider()
            st.caption("**From your portfolio CSV:**")
            for acct_type, bal in _acct.items():
                st.caption(f"{acct_type}: ${bal:,.0f}")

    return profile


# ── Main ──────────────────────────────────────────────────────────────────────

def _breadcrumb(current: str) -> None:
    pages = [
        ("Hub",           "/"),
        ("Portfolio",     "/portfolio"),
        ("Analysis",      "/analysis"),
        ("Wealth Builder",None),
        ("Retirement",    "/retirement"),
    ]
    parts = [f"<strong>{l}</strong>" if l == current else (f'<a href="{p}" target="_self">{l}</a>' if p else l) for l, p in pages]
    st.caption("  ›  ".join(parts), unsafe_allow_html=True)


def main() -> None:
    st.title("Wealth Builder")
    _breadcrumb("Wealth Builder")
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

    # ── Handoff banner ────────────────────────────────────────────────────
    st.divider()
    _bh1, _bh2 = st.columns(2)
    _bh1.page_link("pages/1_Portfolio.py",  label="← Portfolio IA — what do I own?")
    _bh2.page_link("pages/7_Retirement.py", label="Retirement Planner — when can I stop? →")

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
