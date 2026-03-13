"""
Auri Analysis — pages/5_Analysis.py

Portfolio commentary, target allocation, concentration alerts, and policy compliance.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.dashboard_cache import (
    generate_commentary,
    load_allocation,
    load_suggested_targets,
    load_summary,
    save_targets,
)


def _fmt_delta(v: float) -> str:
    """Format a signed percentage deviation with + sign."""
    return f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"


def _targets_editor(
    initial_targets: dict,
    tolerance_pct: float,
    key_prefix: str = "te",
) -> None:
    """
    Inline editor for sector target weights.

    Renders a number input per sector, a live sum indicator, an "Add sector"
    expander, and Save / Reset buttons.  Persists edits across Streamlit
    rerenders via st.session_state.

    Args:
        initial_targets: {sector: pct} used to seed the editor on first render.
        tolerance_pct:   Starting value for the tolerance band input.
        key_prefix:      Unique prefix so multiple editor instances can coexist.
    """
    _init_key  = f"{key_prefix}__initialized"
    _extra_key = f"{key_prefix}__extra_sectors"
    _tol_key   = f"{key_prefix}__tol"

    # Seed session state on first render only
    if not st.session_state.get(_init_key):
        for sec, val in initial_targets.items():
            st.session_state[f"{key_prefix}__{sec}"] = float(val)
        st.session_state[_tol_key]   = float(tolerance_pct)
        st.session_state[_extra_key] = []
        st.session_state[_init_key]  = True

    all_sectors = list(initial_targets.keys()) + st.session_state.get(_extra_key, [])

    # ── Sector inputs ──────────────────────────────────────────────────────
    h1, h2 = st.columns([4, 2])
    h1.caption("Sector")
    h2.caption("Target %")

    for sec in all_sectors:
        sk = f"{key_prefix}__{sec}"
        c1, c2 = st.columns([4, 2])
        c1.markdown(sec)
        c2.number_input(
            sec,
            min_value=0.0, max_value=100.0, step=0.5,
            key=sk,
            label_visibility="collapsed",
        )

    # ── Live sum indicator ─────────────────────────────────────────────────
    total = sum(
        st.session_state.get(f"{key_prefix}__{s}", 0.0) for s in all_sectors
    )
    diff = round(100.0 - total, 2)
    if abs(diff) < 0.05:
        st.success(f"Total: {total:.1f}%  ✓  Ready to save")
    elif abs(diff) <= 5:
        direction = "unallocated" if diff > 0 else "over-allocated"
        st.warning(f"Total: {total:.1f}%  —  {abs(diff):.1f}pp {direction}")
    else:
        st.error(f"Total: {total:.1f}%  —  must equal 100% (currently {'+' if diff < 0 else ''}{-diff:.1f}pp off)")

    st.number_input(
        "Tolerance band (±pp)",
        min_value=1.0, max_value=20.0, step=0.5,
        help="Sectors within this band of their target are considered 'on target'.",
        key=_tol_key,
    )

    # ── Add sector ─────────────────────────────────────────────────────────
    with st.expander("Add a sector"):
        na1, na2, na3 = st.columns([3, 2, 1])
        new_name = na1.text_input(
            "Name", key=f"{key_prefix}__new_name", label_visibility="collapsed",
            placeholder="Sector name",
        )
        new_val = na2.number_input(
            "Value", min_value=0.0, max_value=100.0, step=0.5, value=0.0,
            key=f"{key_prefix}__new_val", label_visibility="collapsed",
        )
        if na3.button("Add", key=f"{key_prefix}__add_btn"):
            name_clean = (new_name or "").strip()
            if name_clean and name_clean not in all_sectors:
                extras = st.session_state.get(_extra_key, [])
                extras.append(name_clean)
                st.session_state[_extra_key] = extras
                st.session_state[f"{key_prefix}__{name_clean}"] = float(new_val)
                st.rerun()
            elif not name_clean:
                st.warning("Enter a sector name first.")
            else:
                st.warning(f"'{name_clean}' is already in the list.")

    # ── Actions ────────────────────────────────────────────────────────────
    can_save = abs(diff) < 0.05
    b1, b2 = st.columns([1, 1])

    if b1.button("Save targets", type="primary", disabled=not can_save,
                 key=f"{key_prefix}__save"):
        targets_out = {
            s: st.session_state.get(f"{key_prefix}__{s}", 0.0)
            for s in all_sectors
            if st.session_state.get(f"{key_prefix}__{s}", 0.0) > 0
        }
        tol_out = st.session_state.get(_tol_key, 5.0)
        with st.spinner("Saving targets.yaml…"):
            result = save_targets(targets_out, tol_out)
        if "error" in result:
            st.error(result["error"])
        else:
            # Clear editor + suggestion state so pages reflect the new file
            for sk in [_init_key, _extra_key, _tol_key] + [
                f"{key_prefix}__{s}" for s in all_sectors
            ]:
                st.session_state.pop(sk, None)
            st.session_state.pop("_target_suggestion", None)
            load_allocation.clear()
            st.rerun()

    if b2.button("Reset", key=f"{key_prefix}__reset",
                 help="Discard edits and reload original values."):
        for sk in [_init_key, _extra_key, _tol_key] + [
            f"{key_prefix}__{s}" for s in all_sectors
        ]:
            st.session_state.pop(sk, None)
        st.rerun()


def _scenario_stress_test(summary: dict) -> None:
    """
    Rule-based scenario stress test.

    Applies estimated sector-level sensitivity coefficients to current weights
    and shows the approximate portfolio value change under each scenario.
    All calculations are local — no network calls.
    """
    st.subheader("Scenario Stress Test")
    st.caption(
        "Estimated portfolio impact under simplified macro scenarios. "
        "Coefficients are illustrative — actual returns will vary by holding."
    )

    # {scenario_label: {sector_keyword: pct_change}}
    # Keywords matched case-insensitively as substrings of actual sector names.
    SCENARIOS: dict[str, dict[str, float]] = {
        "Rate +1% (hawkish)": {
            "fixed income": -8.0,
            "real estate":  -5.0,
            "money market": +2.0,
            "financials":   +3.0,
            "utilities":    -4.0,
        },
        "Rate -1% (dovish)": {
            "fixed income": +8.0,
            "real estate":  +5.0,
            "money market": -1.0,
            "financials":   -2.0,
            "utilities":    +4.0,
        },
        "TSX Correction -20%": {
            "equities - canada": -20.0,
            "financials":        -16.0,
            "energy":            -18.0,
            "real estate":        -8.0,
        },
        "Equity Bear Market -30%": {
            "equities - canada":        -30.0,
            "equities - us":            -30.0,
            "equities - international": -28.0,
            "equities - emerging":      -35.0,
            "financials":               -25.0,
            "energy":                   -25.0,
            "healthcare":               -15.0,
            "real estate":              -10.0,
        },
        "Oil Shock -40%": {
            "energy":            -40.0,
            "equities - canada": -10.0,
        },
        "CAD Weakens -10% vs USD": {
            "equities - us":            +10.0,
            "equities - international": +8.0,
            "equities - emerging":      +6.0,
        },
        "Inflation Spike +3%": {
            "fixed income":      -12.0,
            "real estate":       +5.0,
            "energy":            +8.0,
            "equities - us":     -5.0,
            "equities - canada": -3.0,
            "money market":      +1.0,
        },
    }

    total_mv   = summary.get("total_market_value", 0)
    sector_wts = summary.get("sector_weights_pct", {})

    if not total_mv or not sector_wts:
        st.info("No portfolio data available for stress test.")
        return

    selected = st.selectbox(
        "Select scenario",
        options=list(SCENARIOS.keys()),
        key="stress_scenario",
    )
    impacts = SCENARIOS[selected]

    rows: list[dict] = []
    total_delta = 0.0

    for sector, wt_pct in sorted(sector_wts.items(), key=lambda x: x[1], reverse=True):
        sector_mv = total_mv * wt_pct / 100
        coeff = 0.0
        for kw, chg in impacts.items():
            if kw.lower() in sector.lower():
                coeff = chg
                break
        sector_delta  = round(sector_mv * coeff / 100, 2)
        total_delta  += sector_delta
        rows.append({
            "Sector":            sector,
            "Current Weight %":  round(wt_pct, 1),
            "Current Value ($)": round(sector_mv, 0),
            "Scenario Impact %": round(coeff, 1),
            "Est. Change ($)":   sector_delta,
        })

    new_mv     = total_mv + total_delta
    change_pct = round(total_delta / total_mv * 100, 1) if total_mv else 0.0

    s1, s2, s3 = st.columns(3)
    s1.metric("Current Portfolio Value",        f"${total_mv:,.0f}")
    s2.metric(
        "Est. Value After Scenario",
        f"${new_mv:,.0f}",
        delta=f"${total_delta:+,.0f}",
        delta_color="inverse" if total_delta < 0 else "normal",
    )
    s3.metric(
        "Est. Portfolio Change",
        f"{change_pct:+.1f}%",
        delta_color="inverse" if change_pct < 0 else "normal",
    )

    def _color_stress(row):
        v = row.get("Est. Change ($)", 0) or 0
        if v < -1000:
            return ["background-color: #fdecea"] * len(row)
        if v > 1000:
            return ["background-color: #e8f5e9"] * len(row)
        return [""] * len(row)

    st.dataframe(
        pd.DataFrame(rows).style.apply(_color_stress, axis=1),
        column_config={
            "Current Weight %":  st.column_config.NumberColumn("Weight %",          format="%.1f%%"),
            "Current Value ($)": st.column_config.NumberColumn("Current Value",     format="dollar"),
            "Scenario Impact %": st.column_config.NumberColumn("Impact Coeff %",    format="%.1f%%"),
            "Est. Change ($)":   st.column_config.NumberColumn("Est. Change",       format="dollar"),
        },
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Coefficients are approximate directional estimates for Canadian retail portfolios. "
        "Sectors with no defined sensitivity show 0% — they may still be affected indirectly."
    )


def _breadcrumb(current: str) -> None:
    pages = [
        ("Hub",           "/"),
        ("Portfolio",     "/portfolio"),
        ("Analysis",      None),
        ("Wealth Builder","/wealthbuilder"),
        ("Retirement",    "/retirement"),
    ]
    parts = [f"<strong>{l}</strong>" if l == current else (f'<a href="{p}" target="_self">{l}</a>' if p else l) for l, p in pages]
    st.caption("  ›  ".join(parts), unsafe_allow_html=True)


def main() -> None:
    st.title("Portfolio Analysis")
    _breadcrumb("Analysis")

    if st.button("Refresh"):
        load_summary.clear()
        load_allocation.clear()
        st.session_state.pop("commentary", None)
        st.rerun()

    with st.spinner("Loading portfolio summary…"):
        summary = load_summary()

    if "error" in summary:
        st.error(summary["error"])
        st.stop()

    # ── Commentary ────────────────────────────────────────────────────────
    st.subheader("Portfolio Commentary")

    _c1, _c2, _c3 = st.columns([1, 1, 5])
    def _save_commentary(result: dict) -> None:
        """Persist commentary to data/derived/ so the report builder can include it."""
        try:
            out = Path(__file__).resolve().parent.parent / "data" / "derived" / "commentary_latest.json"
            result_to_save = {**result, "saved_at": datetime.now().isoformat()}
            out.write_text(json.dumps(result_to_save, ensure_ascii=False, indent=2))
        except Exception:
            pass  # non-fatal

    with _c1:
        if st.button("Generate Commentary", help="Observations and clarifying questions about the current portfolio"):
            with st.spinner("Generating commentary — this may take up to a minute…"):
                _r = generate_commentary(mode="standard")
                st.session_state["commentary"] = _r
                _save_commentary(_r)
    with _c2:
        if st.button("Challenge my portfolio", type="primary",
                     help="Adversarial second opinion: risks, allocation challenges, contrarian thesis"):
            with st.spinner("Generating challenge analysis — this may take up to a minute…"):
                _r = generate_commentary(mode="challenge")
                st.session_state["commentary"] = _r
                _save_commentary(_r)
    with _c3:
        if st.session_state.get("commentary") and st.button("Clear"):
            st.session_state.pop("commentary", None)
            st.rerun()

    _commentary_result = st.session_state.get("commentary")
    if _commentary_result:
        if "error" in _commentary_result:
            st.error(_commentary_result["error"])
        else:
            _mode_label = "Challenge Analysis" if _commentary_result.get("mode") == "challenge" else "Commentary"
            if _commentary_result.get("mode") == "challenge":
                st.info("**Challenge mode** — adversarial second opinion · This analysis is intentionally critical to surface blind spots.", icon="⚖️")
            st.markdown(_commentary_result["commentary"].replace("$", "\\$"))
            st.caption(
                f"{_mode_label}  ·  Provider: {_commentary_result.get('provider_used', '—')}  ·  "
                f"Prompt: {_commentary_result.get('prompt_length', 0):,} chars"
            )

    st.divider()

    # ── Target Allocation ─────────────────────────────────────────────────
    st.subheader("Target Allocation")

    alloc = load_allocation()

    if alloc.get("error") == "no_targets_file":
        st.info(
            "No target allocation defined yet.  "
            "You can generate a suggestion based on your risk score, "
            "or create `data/portfolio/targets.yaml` manually."
        )

        _sug_btn, _sug_status = st.columns([1, 5])
        with _sug_btn:
            _clicked_suggest = st.button("Suggest from Risk Score", type="primary")

        if _clicked_suggest:
            with st.spinner("Loading risk profile…"):
                sug = load_suggested_targets()
            st.session_state["_target_suggestion"] = sug

        _sug = st.session_state.get("_target_suggestion")
        if _sug:
            if "error" in _sug:
                err = _sug["error"]
                if err == "no_profile":
                    st.warning(
                        "No risk profile found. Complete the Risk Profile wizard first "
                        "(sidebar → Risk Profile)."
                    )
                elif err == "no_risk_score":
                    st.warning(
                        "Risk profile exists but no score has been computed yet. "
                        "Open Risk Profile and click **Compute Score**."
                    )
                else:
                    st.error(err)
            else:
                score  = _sug["risk_score"]
                label  = _sug["risk_label"]
                tol    = _sug["tolerance_pct"]
                t_dict = _sug["targets"]

                st.success(
                    f"Suggested allocation for **{label}** investor "
                    f"(risk score {score:.0f}/100)  ·  Adjust below, then save."
                )
                _targets_editor(t_dict, tol, key_prefix="sug_editor")
    elif "error" in alloc:
        st.error(alloc["error"])
    else:
        rows         = alloc.get("rows", [])
        untracked    = alloc.get("untracked", [])
        total_mv     = alloc.get("total_market_value", 0)
        target_sum   = alloc.get("target_sum_pct", 0)
        tolerance    = alloc.get("tolerance_pct", 5.0)

        if target_sum != 100.0:
            gap = round(100.0 - target_sum, 1)
            st.caption(
                f"Target weights sum to {target_sum:.1f}% "
                f"({'unallocated: ' if gap > 0 else 'over-allocated: '}{abs(gap):.1f}%)"
            )

        # ── Summary metrics ───────────────────────────────────────────────
        over  = [r for r in rows if r["status"] == "over"]
        under = [r for r in rows if r["status"] == "under"]
        on    = [r for r in rows if r["status"] == "on_target"]

        m1, m2, m3 = st.columns(3)
        m1.metric("On Target", len(on),   help=f"Within ±{tolerance:.0f}pp of target")
        m2.metric("Overweight", len(over),  delta=f"+{len(over)}" if over else None,
                  delta_color="inverse")
        m3.metric("Underweight", len(under), delta=f"-{len(under)}" if under else None,
                  delta_color="inverse")

        # ── Actual vs Target bar chart ─────────────────────────────────────
        if rows:
            chart_df = (
                pd.DataFrame(rows)
                .set_index("asset_class")[["actual_pct", "target_pct"]]
                .rename(columns={"actual_pct": "Actual %", "target_pct": "Target %"})
                .sort_values("Target %", ascending=False)
            )
            st.bar_chart(chart_df, use_container_width=True)

        # ── Deviation table ────────────────────────────────────────────────
        dev_df = pd.DataFrame(rows).rename(columns={
            "asset_class":      "Sector",
            "actual_pct":       "Actual %",
            "target_pct":       "Target %",
            "deviation_pct":    "Deviation",
            "actual_value":     "Current Value",
            "target_value":     "Target Value",
            "rebalance_amount": "Trade Amount",
            "status":           "Status",
        })

        def _color_allocation(row):
            dev = row.get("Deviation", 0) or 0
            if dev > tolerance:
                return ["background-color: #fff3cd"] * len(row)
            if dev < -tolerance:
                return ["background-color: #fdecea"] * len(row)
            return ["background-color: #e8f5e9"] * len(row)

        st.dataframe(
            dev_df[["Sector", "Actual %", "Target %", "Deviation", "Current Value", "Target Value", "Trade Amount"]]
            .style.apply(_color_allocation, axis=1),
            column_config={
                "Actual %":      st.column_config.NumberColumn("Actual %",      format="%.1f%%"),
                "Target %":      st.column_config.NumberColumn("Target %",      format="%.1f%%"),
                "Deviation":     st.column_config.NumberColumn("Deviation (pp)", format="%.1f"),
                "Current Value": st.column_config.NumberColumn("Current Value", format="dollar"),
                "Target Value":  st.column_config.NumberColumn("Target Value",  format="dollar"),
                "Trade Amount":  st.column_config.NumberColumn("Trade Amount",  format="dollar"),
            },
            use_container_width=True,
            hide_index=True,
        )

        # ── Rebalancing trades ─────────────────────────────────────────────
        trades = [r for r in rows if r["status"] != "on_target"]
        if trades:
            st.subheader("Rebalancing Trades")
            st.caption(
                f"Approximate trades to reach target weights · "
                f"Total portfolio: ${total_mv:,.0f}  ·  "
                f"Tax tip: prefer selling in registered (TFSA/RRSP) accounts to avoid capital gains."
            )
            for r in sorted(trades, key=lambda x: abs(x["rebalance_amount"]), reverse=True):
                amt    = r["rebalance_amount"]
                action = "Buy" if amt > 0 else "Sell"
                color  = "#e8f5e9" if amt > 0 else "#fdecea"
                delta  = _fmt_delta(r["deviation_pct"])

                # Tax-aware account guidance
                acct      = r.get("account_breakdown", {})
                reg_val   = acct.get("registered",     0.0)
                nreg_val  = acct.get("non_registered", 0.0)
                uncl_val  = acct.get("unclassified",   0.0)
                acct_parts = []
                if reg_val   > 0: acct_parts.append(f"Registered ${reg_val:,.0f}")
                if nreg_val  > 0: acct_parts.append(f"Non-Reg ${nreg_val:,.0f}")
                if uncl_val  > 0: acct_parts.append(f"Unclassified ${uncl_val:,.0f}")
                acct_line = "  ·  ".join(acct_parts) if acct_parts else ""

                # Tax warning: suggest sell in registered first
                tax_note = ""
                if action == "Sell" and nreg_val > 0 and reg_val > 0:
                    tax_note = ' <span style="color:#b45309;font-size:0.85em"> ⚠ Consider selling registered portion first (tax-sheltered)</span>'
                elif action == "Sell" and nreg_val > 0 and reg_val == 0:
                    tax_note = ' <span style="color:#b71c1c;font-size:0.85em"> ⚠ All holdings in non-registered — sale may trigger capital gains</span>'

                st.markdown(
                    f'<div style="background:{color};padding:6px 12px;border-radius:4px;margin:3px 0">'
                    f'<b>{action} {r["asset_class"]}</b> — '
                    f'${abs(amt):,.0f}'
                    f'{tax_note}  '
                    f'<br><span style="color:#555;font-size:0.85em">'
                    f'{delta} vs target · currently {r["actual_pct"]:.1f}%, target {r["target_pct"]:.1f}%'
                    + (f'  ·  Holdings: {acct_line}' if acct_line else "")
                    + f'</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        if untracked:
            names = ", ".join(r["asset_class"] for r in untracked)
            st.caption(f"Asset classes in portfolio but not in targets: {names}")

        # ── Edit Targets ───────────────────────────────────────────────────
        with st.expander("Edit Target Allocation"):
            st.caption(
                "Adjust sector weights and click **Save targets** to update targets.yaml. "
                "The deviation table above will refresh automatically."
            )
            current_targets = {r["asset_class"]: r["target_pct"] for r in rows}
            _targets_editor(current_targets, tolerance, key_prefix="alloc_editor")

    st.divider()

    # ── Concentration Alerts ──────────────────────────────────────────────
    threshold_pct = summary.get("concentration_threshold_pct", 10.0)
    flags = summary.get("concentration_flags", [])
    st.subheader(f"Concentration Alerts  (>{threshold_pct}%)")

    if flags:
        flags_df = (
            pd.DataFrame(flags)
            .rename(columns={
                "symbol":     "Symbol",
                "weight_pct": "Weight (%)",
                "flag":       "Flag",
            })
        )
        styled = flags_df.style.apply(
            lambda row: ["background-color: #ffcccc"] * len(row), axis=1
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.success(f"No positions above the {threshold_pct}% concentration threshold.")

    st.divider()

    # ── Policy Compliance ─────────────────────────────────────────────────
    policy_flags = summary.get("policy_flags", [])
    if policy_flags:
        breaches = [f for f in policy_flags if f["severity"] == "breach"]
        warnings = [f for f in policy_flags if f["severity"] == "warning"]
        st.subheader(
            f"Policy Compliance  —  {len(breaches)} breach{'es' if len(breaches) != 1 else ''}, "
            f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}"
        )
        policy_df = (
            pd.DataFrame(policy_flags)
            .rename(columns={
                "type":      "Type",
                "name":      "Name",
                "value_pct": "Actual (%)",
                "limit_pct": "Limit (%)",
                "severity":  "Severity",
                "message":   "Detail",
            })
        )

        def _color_policy(row):
            color = "#ffcccc" if row["Severity"] == "breach" else "#fff3cd"
            return [f"background-color: {color}"] * len(row)

        st.dataframe(
            policy_df[["Severity", "Type", "Name", "Actual (%)", "Limit (%)", "Detail"]]
            .style.apply(_color_policy, axis=1),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("No policy flags.")

    st.divider()

    # ── Scenario Stress Test ───────────────────────────────────────────────
    # Use live prices if Refresh Prices was run on the dashboard — recomputes
    # sector totals from position-level live MV so the stress test reflects
    # current market values, not the CSV export date.
    _stress_summary = summary
    _price_data = st.session_state.get("price_data")
    if _price_data and "error" not in _price_data and _price_data.get("price_data"):
        _pd_map = _price_data["price_data"]
        _live_sector: dict[str, float] = {}
        _live_total = 0.0
        for _pos in summary.get("positions_summary", []):
            _sym    = str(_pos.get("symbol", "")).upper()
            _qty    = float(_pos.get("quantity") or 0)
            _csv_mv = float(_pos.get("market_value") or 0)
            _lpx    = _pd_map.get(_sym, {}).get("price")
            _pos_mv = (_lpx * _qty) if (_lpx and _qty) else _csv_mv
            _sec    = str(_pos.get("sector") or "Unknown")
            _live_sector[_sec] = _live_sector.get(_sec, 0.0) + _pos_mv
            _live_total += _pos_mv
        if _live_total > 0:
            _live_wts = {s: round(v / _live_total * 100, 2) for s, v in _live_sector.items()}
            _stress_summary = {
                **summary,
                "total_market_value": round(_live_total, 2),
                "sector_weights_pct": _live_wts,
            }

    _scenario_stress_test(_stress_summary)


if __name__ == "__main__":
    main()
