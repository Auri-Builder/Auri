"""
ORI Portfolio Dashboard — Phase A

Consumes portfolio_summary_v0 output only. No raw CSV reading.

Default mode (governed):
    Submits a portfolio_summary_v0 job via the ORI job queue.
    Requires core/job_runner.py to be running in a separate terminal.

Dev shortcut:
    Create dashboard.yaml at repo root with:
        dev_direct_call: true
    The handler is then called directly — no job runner needed.

Run:
    streamlit run app.py
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from core.dashboard_cache import fetch_benchmark, load_allocation, load_dashboard_config, load_summary

from core._paths import PROJECT_ROOT, get_data_dir  # noqa: F401


# ---------------------------------------------------------------------------
# Config + data loading
# ---------------------------------------------------------------------------

def _fetch_prices() -> dict:
    """
    Call portfolio_prices_v0 — direct in dev mode, governed queue otherwise.
    *** Makes outbound network calls to Yahoo Finance. ***
    """
    dash_cfg = load_dashboard_config()
    if dash_cfg.get("dev_direct_call"):
        from core.job_runner import handle_portfolio_prices_v0  # noqa: PLC0415
        return handle_portfolio_prices_v0({})
    from core.oricore import submit_and_wait  # noqa: PLC0415
    result = submit_and_wait(
        "portfolio_prices_v0", {}, {"approval_required": False}, timeout=120
    )
    if result is None:
        return {"error": "Price fetch job timed out."}
    if result.get("status") != "ok":
        return {"error": result.get("error", "Price fetch job failed.")}
    return result["output"]


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _fmt_cad(value: float) -> str:
    return f"${value:,.2f}"


def _bucket_label(key: str) -> str:
    return key.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _breadcrumb(current: str) -> None:
    pages = [
        ("Hub",           "/"),
        ("Portfolio",     None),
        ("Analysis",      "/analysis"),
        ("Wealth Builder","/wealthbuilder"),
        ("Retirement",    "/retirement"),
    ]
    parts = []
    for label, page in pages:
        if label == current:
            parts.append(f"<strong>{label}</strong>")
        else:
            parts.append(f'<a href="{page}" target="_self">{label}</a>' if page else label)
    st.caption("  ›  ".join(parts), unsafe_allow_html=True)


def main() -> None:
    st.title("Portfolio Dashboard")
    _breadcrumb("Portfolio")
    st.caption("Live prices · sector analysis · income tracking · offline by default")

    # Reload CSV clears the summary cache and all derived session state.
    if st.button("Reload CSV", help="Re-process the uploaded CSV files. Does not fetch live prices."):
        load_summary.clear()
        load_allocation.clear()
        st.session_state.pop("price_data",      None)
        st.session_state.pop("benchmark_data",  None)
        st.rerun()

    with st.spinner("Loading portfolio summary…"):
        summary = load_summary()

    if "error" in summary:
        st.error(summary["error"])
        st.stop()

    # ── Onboarding / setup checklist ─────────────────────────────────────
    _profile_path  = get_data_dir() / "portfolio" / "profile.yaml"
    _targets_path  = get_data_dir() / "portfolio" / "targets.yaml"
    _derived_dir   = get_data_dir() / "derived"
    _has_data      = "error" not in summary
    _has_answers   = (get_data_dir() / "portfolio" / "answers.yaml").exists()
    _has_risk      = False
    _has_targets   = _targets_path.exists()
    _has_snapshots = any(_derived_dir.glob("*.json")) if _derived_dir.exists() else False

    if _profile_path.exists():
        try:
            import yaml as _yaml
            _prof = _yaml.safe_load(_profile_path.read_text()) or {}
            _has_risk = (_prof.get("derived") or {}).get("risk_score") is not None
        except Exception:
            pass

    # (label, done, page_link, link_text)
    _steps = [
        ("Portfolio data loaded",        _has_data,      "pages/wizard.py",      "Upload Wizard →"),
        ("Investor questionnaire done",  _has_answers,   "pages/profile.py",     "Complete Questionnaire →"),
        ("Risk score computed",          _has_risk,      "pages/profile.py",     "Run Scorer →"),
        ("Target allocation defined",    _has_targets,   "pages/5_Analysis.py",  "Suggest from Risk Score →"),
        ("First snapshot saved",         _has_snapshots, "pages/snapshots.py",   "Create Snapshot →"),
    ]
    _incomplete = [s for s in _steps if not s[1]]

    if _incomplete:
        with st.expander(f"Setup checklist  —  {len(_incomplete)} step{'s' if len(_incomplete) != 1 else ''} remaining", expanded=False):
            for label, done, page, link_text in _steps:
                icon = "✅" if done else "⬜"
                if done:
                    st.markdown(f"{icon} {label}")
                else:
                    _sc1, _sc2 = st.columns([4, 1])
                    _sc1.markdown(f"{icon} **{label}**")
                    _sc2.page_link(page, label=link_text)

    # ── Allocation drift banner ───────────────────────────────────────────
    _alloc = load_allocation()
    if "error" not in _alloc:
        _over  = [r for r in _alloc.get("rows", []) if r["status"] == "over"]
        _under = [r for r in _alloc.get("rows", []) if r["status"] == "under"]
        _tol   = _alloc.get("tolerance_pct", 5.0)
        if _over or _under:
            _parts = []
            for r in sorted(_over + _under, key=lambda x: abs(x["deviation_pct"]), reverse=True):
                sign  = "+" if r["deviation_pct"] > 0 else ""
                _parts.append(f"{r['asset_class']} ({sign}{r['deviation_pct']:.1f}pp)")
            _msg = "  ·  ".join(_parts)
            st.warning(
                f"**Allocation drift** outside ±{_tol:.0f}pp tolerance: {_msg}",
                icon="⚖️",
            )
            st.page_link("pages/5_Analysis.py", label="View target allocation →")

    # ── Row 1: Key metrics ────────────────────────────────────────────────
    # Compute live total market value if prices have been fetched
    _price_result = st.session_state.get("price_data")
    _live_total_mv: float | None = None
    if _price_result and "error" not in _price_result and _price_result.get("price_data"):
        _pd_map = _price_result["price_data"]
        _live_total = 0.0
        for _pos in summary.get("positions_summary", []):
            _sym  = str(_pos.get("symbol", "")).upper()
            _qty  = float(_pos.get("quantity") or 0)
            _lpx  = _pd_map.get(_sym, {}).get("price")
            _live_total += (_lpx * _qty) if (_lpx and _qty) else float(_pos.get("market_value") or 0)
        _live_total_mv = round(_live_total, 2)

    _csv_tmv = summary.get("total_market_value", 0)
    col1, col2, col3 = st.columns(3)
    if _live_total_mv is not None:
        _tmv_delta = round(_live_total_mv - _csv_tmv, 2)
        col1.metric(
            "Total Market Value",
            _fmt_cad(_live_total_mv),
            delta=f"{'+' if _tmv_delta >= 0 else ''}{_fmt_cad(_tmv_delta)} vs CSV",
            help=f"Live prices applied. CSV value (at export): {_fmt_cad(_csv_tmv)}",
        )
    else:
        col1.metric("Total Market Value", _fmt_cad(_csv_tmv))
    col2.metric("Positions", summary.get("position_count", 0))
    col3.metric("Unique Symbols", summary.get("unique_symbols", 0))

    # ── Row 1b: Cost-basis metrics ────────────────────────────────────────
    tcb  = summary.get("total_cost_basis")
    tug  = summary.get("total_unrealized_gain")
    tugp = summary.get("total_unrealized_gain_pct")
    col4, col5, col6 = st.columns(3)
    col4.metric("Total Cost Basis",    _fmt_cad(tcb)  if tcb  is not None else "—")
    col5.metric("Unrealized Gain",     _fmt_cad(tug)  if tug  is not None else "—")
    col6.metric("Unrealized Gain (%)", f"{tugp:.2f}%" if tugp is not None else "—")

    # ── Row 1c: Live prices + dividend income ─────────────────────────────
    price_result = st.session_state.get("price_data")
    income_summary = price_result.get("income_summary", {}) if price_result and "error" not in price_result else {}

    _p_btn, _p_clr, _p_info = st.columns([1, 1, 5])
    with _p_btn:
        if st.button("Refresh Prices", help="Fetches live prices from Yahoo Finance (network call)"):
            with st.spinner("Fetching live prices and dividend data…"):
                st.session_state["price_data"] = _fetch_prices()
            st.rerun()
    with _p_clr:
        if price_result and st.button("Clear Prices"):
            st.session_state.pop("price_data", None)
            st.rerun()
    with _p_info:
        if price_result and "error" not in price_result:
            fetched_at = price_result.get("fetched_at", "—")
            fc = price_result.get("fetched_count", 0)
            sc = price_result.get("stale_count", 0)
            st.caption(f"Prices as of {fetched_at}  ·  {fc} live, {sc} stale/no-data")

    if price_result and "error" in price_result:
        st.error(price_result["error"])

    if income_summary:
        cad_income = income_summary.get("total_annual_income_cad")
        usd_income = income_summary.get("total_annual_income_usd")
        _tmv_for_yield = _live_total_mv or summary.get("total_market_value") or 1
        cad_yield  = (
            round(cad_income / _tmv_for_yield * 100, 2)
            if cad_income and _tmv_for_yield
            else None
        )

        # Income coverage ratio — portfolio income vs. retirement funding gap
        _coverage_pct   = None
        _coverage_delta = None
        _coverage_help  = None
        if _profile_path.exists():
            try:
                import yaml as _yaml2
                _ret = (_yaml2.safe_load(_profile_path.read_text()) or {}).get("retirement", {})
                _annual_exp  = _ret.get("annual_expenses_estimate")
                _guar_pct    = _ret.get("guaranteed_income_pct") or 0
                if _annual_exp and _annual_exp > 0 and cad_income is not None:
                    _guar_income  = _annual_exp * _guar_pct / 100
                    _funding_gap  = _annual_exp - _guar_income
                    if _funding_gap > 0:
                        _coverage_pct   = round(cad_income / _funding_gap * 100, 1)
                        _coverage_delta = f"${cad_income:,.0f} income vs ${_funding_gap:,.0f} gap"
                        _coverage_help  = (
                            f"Annual expenses ${_annual_exp:,.0f}  ·  "
                            f"Guaranteed income ${_guar_income:,.0f} ({_guar_pct:.0f}%)  ·  "
                            f"Funding gap ${_funding_gap:,.0f}"
                        )
            except Exception:
                pass

        _ic1, _ic2, _ic3, _ic4 = st.columns(4)
        _ic1.metric(
            "Est. Annual Income (CAD)",
            _fmt_cad(cad_income) if cad_income is not None else "—",
        )
        _ic2.metric(
            "Portfolio Yield (CAD)",
            f"{cad_yield:.2f}%" if cad_yield is not None else "—",
        )
        _ic3.metric(
            "Est. Annual Income (USD)",
            f"${usd_income:,.2f}" if usd_income is not None else "—",
            help="USD positions reported separately — no FX conversion applied",
        )
        _ic4.metric(
            "Income Coverage",
            f"{_coverage_pct:.0f}%" if _coverage_pct is not None else "—",
            delta=_coverage_delta,
            help=_coverage_help or "Set annual expenses in Investor Profile → Investment Approach to see coverage ratio",
        )

    # ── Benchmark comparison ──────────────────────────────────────────────
    from agents.ori_ia.market_data import BENCHMARKS  # noqa: PLC0415

    _bm_result = st.session_state.get("benchmark_data")
    _bm_col1, _bm_col2, _bm_col3 = st.columns([2, 1, 4])
    with _bm_col1:
        _bm_label = st.selectbox(
            "Benchmark",
            options=list(BENCHMARKS.keys()),
            key="benchmark_select",
            label_visibility="collapsed",
        )
    with _bm_col2:
        if st.button("Compare vs Benchmark", help="Fetch YTD benchmark return from Yahoo Finance"):
            with st.spinner(f"Fetching {BENCHMARKS[_bm_label]}…"):
                st.session_state["benchmark_data"] = fetch_benchmark(BENCHMARKS[_bm_label])
            st.rerun()
    with _bm_col3:
        if _bm_result:
            if "error" in _bm_result:
                st.error(_bm_result["error"])
            elif not _bm_result.get("stale"):
                _bm_ret   = _bm_result.get("return_pct")
                _bm_from  = _bm_result.get("from_date", "")
                _bm_to    = _bm_result.get("to_date", "")
                _bm_sym   = _bm_result.get("symbol", "")

                # Portfolio return (unrealized gain / cost basis — approximate)
                _port_ret = None
                _tcb_bm   = summary.get("total_cost_basis")
                _tmv_bm   = summary.get("total_market_value")
                if _tcb_bm and _tmv_bm and _tcb_bm > 0:
                    _port_ret = round((_tmv_bm - _tcb_bm) / _tcb_bm * 100, 2)

                _bm_b1, _bm_b2, _bm_b3 = st.columns(3)
                _bm_b1.metric(
                    f"{_bm_sym} Return ({_bm_from[:4]})",
                    f"{_bm_ret:+.1f}%" if _bm_ret is not None else "—",
                )
                _bm_b2.metric(
                    "Portfolio Return (unrealized)",
                    f"{_port_ret:+.1f}%" if _port_ret is not None else "—",
                    help="(Market Value − Cost Basis) / Cost Basis. Not time-weighted — use snapshots for period returns.",
                )
                if _bm_ret is not None and _port_ret is not None:
                    _alpha = round(_port_ret - _bm_ret, 1)
                    _bm_b3.metric(
                        "vs Benchmark",
                        f"{_alpha:+.1f}pp",
                        delta=f"{'Outperforming' if _alpha >= 0 else 'Underperforming'} by {abs(_alpha):.1f}pp",
                        delta_color="normal" if _alpha >= 0 else "inverse",
                    )
            else:
                st.warning(f"Benchmark data stale: {_bm_result.get('stale_reason', '—')}")

    st.divider()

    # ── Row 2: Sector weights + Account type split ────────────────────────
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("Sector Weights")
        sector_data = summary.get("sector_weights_pct", {})
        if sector_data:
            sector_df = (
                pd.DataFrame(sector_data.items(), columns=["Sector", "Weight (%)"])
                .sort_values("Weight (%)", ascending=True)
                .set_index("Sector")
            )
            st.bar_chart(sector_df)
        else:
            st.info("No sector data available.")

    with col_right:
        st.subheader("Account Type Split")
        # When live prices are available, recompute split from positions so
        # the registered/non-reg breakdown reflects current market values.
        _split_source = "CSV"
        split = summary.get("account_type_split", {})
        if _live_total_mv is not None and _price_result and "error" not in _price_result:
            _pd_map2   = _price_result.get("price_data", {})
            _live_reg  = 0.0
            _live_nreg = 0.0
            _live_uncl = 0.0
            for _pos in summary.get("positions_summary", []):
                _sym = str(_pos.get("symbol", "")).upper()
                _qty = float(_pos.get("quantity") or 0)
                _csv_mv = float(_pos.get("market_value") or 0)
                _lpx = _pd_map2.get(_sym, {}).get("price")
                _pos_mv = (_lpx * _qty) if (_lpx and _qty) else _csv_mv
                # Scale registered/non-reg ratio from CSV
                if _csv_mv > 0:
                    _ratio = _pos_mv / _csv_mv
                    _live_reg  += float(_pos.get("registered_value")     or 0) * _ratio
                    _live_nreg += float(_pos.get("non_registered_value") or 0) * _ratio
                    _live_uncl += float(_pos.get("unclassified_value")   or 0) * _ratio
            split = {}
            if _live_reg  > 0: split["registered"]     = round(_live_reg,  2)
            if _live_nreg > 0: split["non_registered"]  = round(_live_nreg, 2)
            if _live_uncl > 0: split["unclassified"]    = round(_live_uncl, 2)
            _split_source = "Live"

        total_split = sum(split.values()) if split else 0.0
        for bucket, value in split.items():
            pct = (value / total_split * 100) if total_split > 0 else 0.0
            st.metric(
                _bucket_label(bucket),
                _fmt_cad(value),
                f"{pct:.1f}% of portfolio",
            )
        if split:
            st.caption(f"Values based on {_split_source} prices")

    st.divider()

    # ── Row 3: Top positions ──────────────────────────────────────────────
    st.subheader("Top Positions")
    top = summary.get("top_positions", [])
    if top:
        top_df = (
            pd.DataFrame(top)
            .rename(columns={"symbol": "Symbol", "weight_pct": "Weight (%)"})
        )
        st.dataframe(top_df, use_container_width=True, hide_index=True)
    else:
        st.info("No position data available.")

    st.divider()

    # ── Row 4: Positions breakdown ────────────────────────────────────────
    st.subheader("Positions")
    positions = summary.get("positions_summary", [])

    if not positions:
        st.info("No positions data available.")
    else:
        pos_df = pd.DataFrame(positions)

        # ── P&L summary strip ─────────────────────────────────────────────
        # Computed from the full positions list — not affected by filters below.
        _ug_vals  = [p["unrealized_gain"]     for p in positions if p.get("unrealized_gain")     is not None]
        _ugp_vals = [p["unrealized_gain_pct"] for p in positions if p.get("unrealized_gain_pct") is not None]

        _best_gain  = max(_ug_vals)  if _ug_vals  else None
        _worst_loss = min(_ug_vals)  if _ug_vals  else None
        _high_pct   = max(_ugp_vals) if _ugp_vals else None
        _low_pct    = min(_ugp_vals) if _ugp_vals else None

        _sc1, _sc2, _sc3, _sc4 = st.columns(4)
        _sc1.metric(
            "Largest Gain ($)",
            _fmt_cad(_best_gain)  if _best_gain  is not None and _best_gain  > 0 else "—",
        )
        _sc2.metric(
            "Largest Loss ($)",
            _fmt_cad(_worst_loss) if _worst_loss is not None and _worst_loss < 0 else "—",
        )
        _sc3.metric(
            "Highest Unrealized (%)",
            f"{_high_pct:.2f}%"   if _high_pct  is not None and _high_pct  > 0 else "—",
        )
        _sc4.metric(
            "Lowest Unrealized (%)",
            f"{_low_pct:.2f}%"    if _low_pct   is not None and _low_pct   < 0 else "—",
        )

        # ── Filter controls ───────────────────────────────────────────────
        sectors       = sorted(pos_df["sector"].unique().tolist())
        asset_classes = sorted(pos_df["asset_class"].unique().tolist())

        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            sel_sectors = st.multiselect(
                "Sector",
                options=sectors,
                default=[],
                placeholder="All sectors",
            )
        with f_col2:
            sel_asset_classes = st.multiselect(
                "Asset Class",
                options=asset_classes,
                default=[],
                placeholder="All asset classes",
            )
        with f_col3:
            acct_filter = st.selectbox(
                "Account Type",
                options=["All", "Registered only", "Non-registered only", "Unclassified only"],
            )

        # Apply filters — empty multiselect means no filter (show all).
        mask = pd.Series([True] * len(pos_df), index=pos_df.index)
        if sel_sectors:
            mask &= pos_df["sector"].isin(sel_sectors)
        if sel_asset_classes:
            mask &= pos_df["asset_class"].isin(sel_asset_classes)
        if acct_filter == "Registered only":
            mask &= pos_df["registered_value"] > 0
        elif acct_filter == "Non-registered only":
            mask &= pos_df["non_registered_value"] > 0
        elif acct_filter == "Unclassified only":
            mask &= pos_df["unclassified_value"] > 0

        # Merge live price + dividend data into positions df if available
        if price_result and "error" not in price_result and price_result.get("price_data"):
            pd_map = price_result["price_data"]
            pos_df["Current Price"]  = pos_df["symbol"].map(
                lambda s: pd_map.get(s.upper(), {}).get("price")
            )
            pos_df["Div Yield (%)"]  = pos_df["symbol"].map(
                lambda s: pd_map.get(s.upper(), {}).get("dividend_yield_pct")
            )
            pos_df["Annual Income"]  = pos_df["symbol"].map(
                lambda s: pd_map.get(s.upper(), {}).get("annual_income")
            )
            pos_df["Price Stale"]    = pos_df["symbol"].map(
                lambda s: pd_map.get(s.upper(), {}).get("stale", False)
            )
            # Recalculate market value and P&L from live price + quantity
            def _recalc_mv(row):
                price = row.get("Current Price")
                qty   = row.get("quantity") or 0
                if price and qty:
                    return round(float(price) * float(qty), 2)
                return row.get("market_value")

            pos_df["Live MV"] = pos_df.apply(_recalc_mv, axis=1)
            pos_df["Live Gain"] = pos_df.apply(
                lambda row: round(row["Live MV"] - row["cost_basis"], 2)
                if row.get("cost_basis") and row.get("Live MV") else None,
                axis=1,
            )
        else:
            for col in ["Current Price", "Div Yield (%)", "Annual Income", "Price Stale", "Live MV", "Live Gain"]:
                pos_df[col] = None

        # Rename all columns once; each tab selects its subset
        base = (
            pos_df[mask]
            .drop(columns=["reconciliation_delta", "Price Stale"], errors="ignore")
            .rename(columns={
                "symbol":               "Symbol",
                "security_name":        "Security",
                "sector":               "Sector",
                "asset_class":          "Asset Class",
                "market_value":         "CSV Market Value",
                "quantity":             "Quantity",
                "weight_pct":           "Weight (%)",
                "cost_basis":           "Cost Basis",
                "unrealized_gain":      "Unrealized Gain",
                "unrealized_gain_pct":  "Unrealized Gain (%)",
                "registered_value":     "Registered",
                "non_registered_value": "Non-Reg",
                "unclassified_value":   "Unclassified",
                "account_count":        "Accounts",
                "Live MV":              "Live Market Value",
                "Live Gain":            "Live Gain",
            })
            .sort_values("CSV Market Value", ascending=False)
            .reset_index(drop=True)
        )

        n_shown  = len(base)
        n_total  = len(pos_df)
        st.caption(f"Showing {n_shown} of {n_total} positions")

        tab_holdings, tab_income, tab_pnl, tab_accounts = st.tabs(
            ["Holdings", "Income", "P&L", "Accounts"]
        )

        # ── Holdings tab ──────────────────────────────────────────────────
        with tab_holdings:
            cols = ["Symbol", "Security", "Sector", "Asset Class", "Weight (%)", "CSV Market Value", "Live Market Value"]
            st.dataframe(
                base[cols].sort_values("CSV Market Value", ascending=False),
                column_config={
                    "CSV Market Value":  st.column_config.NumberColumn("CSV Market Value",  format="dollar"),
                    "Live Market Value": st.column_config.NumberColumn("Live Market Value", format="dollar"),
                    "Weight (%)":        st.column_config.NumberColumn("Weight (%)",        format="%.2f%%"),
                },
                use_container_width=True, hide_index=True,
            )

        # ── Income tab ────────────────────────────────────────────────────
        with tab_income:
            inc_cols = ["Symbol", "Security", "Sector", "Current Price", "Div Yield (%)", "Annual Income", "Live Market Value"]
            inc_df = base[inc_cols].sort_values("Annual Income", ascending=False, na_position="last")
            st.dataframe(
                inc_df,
                column_config={
                    "Current Price":     st.column_config.NumberColumn("Current Price",    format="dollar"),
                    "Div Yield (%)":     st.column_config.NumberColumn("Div Yield (%)",    format="%.2f%%"),
                    "Annual Income":     st.column_config.NumberColumn("Annual Income",    format="dollar"),
                    "Live Market Value": st.column_config.NumberColumn("Live Market Value", format="dollar"),
                },
                use_container_width=True, hide_index=True,
            )

        # ── P&L tab ───────────────────────────────────────────────────────
        with tab_pnl:
            pnl_cols = ["Symbol", "Security", "Cost Basis", "Unrealized Gain", "Unrealized Gain (%)", "Live Gain"]
            pnl_df = base[pnl_cols].sort_values("Unrealized Gain", ascending=True, na_position="last")
            st.dataframe(
                pnl_df,
                column_config={
                    "Cost Basis":           st.column_config.NumberColumn("Cost Basis",        format="dollar"),
                    "Unrealized Gain":      st.column_config.NumberColumn("Unrealized Gain",   format="dollar"),
                    "Unrealized Gain (%)":  st.column_config.NumberColumn("Unrealized Gain %", format="%.2f%%"),
                    "Live Gain":            st.column_config.NumberColumn("Live Gain",         format="dollar"),
                },
                use_container_width=True, hide_index=True,
            )

        # ── Accounts tab ──────────────────────────────────────────────────
        with tab_accounts:
            acct_cols = ["Symbol", "Security", "Asset Class", "Registered", "Non-Reg", "Unclassified", "Accounts"]
            st.dataframe(
                base[acct_cols].sort_values("Registered", ascending=False, na_position="last"),
                column_config={
                    "Registered":   st.column_config.NumberColumn("Registered",   format="dollar"),
                    "Non-Reg":      st.column_config.NumberColumn("Non-Reg",      format="dollar"),
                    "Unclassified": st.column_config.NumberColumn("Unclassified", format="dollar"),
                },
                use_container_width=True, hide_index=True,
            )

    # ── Retirement Readiness Score ────────────────────────────────────────
    _retirement_profile_path = get_data_dir() / "retirement" / "retirement_profile.yaml"
    if _retirement_profile_path.exists():
        try:
            import yaml as _yaml
            _rp = _yaml.safe_load(_retirement_profile_path.read_text()) or {}
            _household = _rp.get("household", {})
            _prim      = _household.get("primary", {})
            _spending  = _rp.get("spending", {})

            _spouse_d = _household.get("spouse")
            if _prim and _spending.get("annual_target"):
                from agents.ori_rp.readiness import compute_readiness_score as _crs
                from agents.ori_rp.cashflow import PersonProfile as _PP  # noqa: PLC0415
                _spouse_pp = None
                if _spouse_d:
                    try:
                        _spouse_pp = _PP(
                            current_age            = int(_spouse_d.get("current_age", 65)),
                            rrsp_rrif_balance      = float(_spouse_d.get("rrsp_rrif_balance", 0)),
                            tfsa_balance           = float(_spouse_d.get("tfsa_balance", 0)),
                            non_registered_balance = float(_spouse_d.get("non_registered_balance", 0)),
                            cpp_monthly_at_65      = float(_spouse_d.get("cpp_monthly_at_65", 0)),
                            oas_monthly_at_65      = float(_spouse_d.get("oas_monthly_at_65", 0)),
                            pension_monthly        = float(_spouse_d.get("pension_monthly", 0)),
                            tfsa_room_remaining    = float(_spouse_d.get("tfsa_room_remaining", 20_000)),
                            province               = _prim.get("province", "ON"),
                        )
                    except Exception:
                        _spouse_pp = None
                _readiness = _crs(
                    primary_age         = int(_prim.get("current_age", 65)),
                    rrsp_rrif_balance   = float(_prim.get("rrsp_rrif_balance", 0)),
                    tfsa_balance        = float(_prim.get("tfsa_balance", 0)),
                    non_reg_balance     = float(_prim.get("non_registered_balance", 0)),
                    tfsa_room_remaining = float(_prim.get("tfsa_room_remaining", 0)),
                    cpp_monthly_at_65   = float(_prim.get("cpp_monthly_at_65", 0)),
                    oas_monthly_at_65   = float(_prim.get("oas_monthly_at_65", 0)),
                    pension_monthly     = float(_prim.get("pension_monthly", 0)),
                    cpp_start_age       = int(_prim.get("cpp_start_age", 65)),
                    oas_start_age       = int(_prim.get("oas_start_age", 65)),
                    annual_spending     = float(_spending.get("annual_target", 80_000)),
                    province            = _prim.get("province", "ON"),
                    base_year           = __import__("datetime").date.today().year,
                    spouse              = _spouse_pp,
                    sp_cpp_start_age    = int(_spouse_d.get("cpp_start_age", 65)) if _spouse_d else 0,
                    sp_oas_start_age    = int(_spouse_d.get("oas_start_age", 65)) if _spouse_d else 0,
                )

                st.divider()
                _rs_score = _readiness["score"]
                _rs_label = _readiness["label"]
                _rs_col1, _rs_col2, _rs_col3 = st.columns([1, 1, 4])
                _rs_col1.metric(
                    "Retirement Readiness",
                    f"{_rs_score:.0f} / 100",
                    help="Based on portfolio longevity, income coverage, TFSA utilization, and liquidity. Run Monte Carlo on the Retirement page to improve this score.",
                )
                _rs_col2.metric(
                    "Status",
                    _rs_label,
                    help="90–100 Excellent · 75–89 Good · 60–74 Fair · 40–59 At Risk · <40 Critical",
                )
                _rs_col3.caption(
                    f"Total retirement assets: ${_readiness['total_portfolio']:,.0f} · "
                    f"Guaranteed income: ${_readiness['guaranteed_annual']:,.0f}/yr · "
                    f"[See full breakdown on the Retirement page](7_Retirement)"
                )
        except Exception:
            pass  # Silently skip if retirement planner not installed or profile malformed

    # ── Handoff banner ────────────────────────────────────────────────────
    st.divider()
    _h1, _h2 = st.columns(2)
    _h1.page_link("pages/6_WealthBuilder.py", label="Wealth Builder — am I on track? →")
    _h2.page_link("pages/7_Retirement.py",    label="Retirement Planner — when can I stop? →")

    # ── Footer ────────────────────────────────────────────────────────────
    st.divider()
    st.caption("Accounts loaded:")
    for acct in summary.get("accounts_loaded", []):
        st.caption(
            f"  {acct.get('file', '—')}  —  "
            f"{acct.get('account_type', '—')} @ {acct.get('institution', '—')}"
        )


if __name__ == "__main__":
    main()
