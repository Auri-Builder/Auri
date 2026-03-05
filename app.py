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
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent
DASHBOARD_CONFIG_PATH = PROJECT_ROOT / "dashboard.yaml"


# ---------------------------------------------------------------------------
# Config + data loading
# ---------------------------------------------------------------------------

def _load_dashboard_config() -> dict:
    """
    Load optional dashboard.yaml from repo root.
    Returns {} if the file doesn't exist or is empty.
    """
    if not DASHBOARD_CONFIG_PATH.exists():
        return {}
    with DASHBOARD_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


@st.cache_data(show_spinner=False)
def load_summary() -> dict:
    """
    Fetch the portfolio summary.

    Branches on dashboard.yaml:
      dev_direct_call: true  → call handle_portfolio_summary_v0() directly
      dev_direct_call: false → submit job via governed queue (default)
    """
    dash_cfg = _load_dashboard_config()

    if dash_cfg.get("dev_direct_call"):
        from core.job_runner import handle_portfolio_summary_v0  # noqa: PLC0415
        return handle_portfolio_summary_v0({})

    # Governed path: submit via job queue, approval bypassed by button click.
    from core.oricore import submit_and_wait  # noqa: PLC0415

    result = submit_and_wait(
        "portfolio_summary_v0",
        {},
        {"approval_required": False},
        timeout=30,
    )

    if result is None:
        return {
            "error": (
                "Job timed out — is the job runner active?\n\n"
                "Start it with:  python -m core.job_runner"
            )
        }
    if result.get("status") != "ok":
        return {"error": result.get("error", "Job failed with unknown error")}

    return result["output"]  # unwrap the job envelope


def _fetch_prices() -> dict:
    """
    Call portfolio_prices_v0 — direct in dev mode, governed queue otherwise.
    *** Makes outbound network calls to Yahoo Finance. ***
    """
    dash_cfg = _load_dashboard_config()
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


def _generate_commentary() -> dict:
    """
    Call portfolio_commentary_v0 — direct in dev mode, governed queue otherwise.
    Returns the handler dict (may contain "error" key).
    """
    dash_cfg = _load_dashboard_config()

    if dash_cfg.get("dev_direct_call"):
        from core.job_runner import handle_portfolio_commentary_v0  # noqa: PLC0415
        return handle_portfolio_commentary_v0({})

    from core.oricore import submit_and_wait  # noqa: PLC0415

    result = submit_and_wait(
        "portfolio_commentary_v0",
        {},
        {"approval_required": False},
        timeout=180,  # LLM calls can be slow
    )

    if result is None:
        return {
            "error": (
                "Commentary job timed out — is the job runner active?\n\n"
                "Start it with:  python -m core.job_runner"
            )
        }
    if result.get("status") != "ok":
        return {"error": result.get("error", "Commentary job failed with unknown error")}

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

def main() -> None:
    st.set_page_config(page_title="Auri — Portfolio Dashboard", layout="wide")
    st.title("Auri Portfolio Dashboard")
    st.caption("Personal investment intelligence · offline by default · network calls only on explicit request")

    # Refresh clears the summary cache and all derived session state.
    if st.button("Refresh"):
        load_summary.clear()
        st.session_state.pop("commentary", None)
        st.session_state.pop("price_data", None)
        st.rerun()

    with st.spinner("Loading portfolio summary…"):
        summary = load_summary()

    if "error" in summary:
        st.error(summary["error"])
        st.stop()

    # ── Row 1: Key metrics ────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Market Value", _fmt_cad(summary.get("total_market_value", 0)))
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
        cad_yield  = (
            round(cad_income / summary.get("total_market_value", 1) * 100, 2)
            if cad_income and summary.get("total_market_value")
            else None
        )
        _ic1, _ic2, _ic3 = st.columns(3)
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
        split = summary.get("account_type_split", {})
        total_split = sum(split.values()) if split else 0.0
        for bucket, value in split.items():
            pct = (value / total_split * 100) if total_split > 0 else 0.0
            st.metric(
                _bucket_label(bucket),
                _fmt_cad(value),
                f"{pct:.1f}% of portfolio",
            )

    st.divider()

    # ── Row 3: Top positions ──────────────────────────────────────────────
    st.subheader("Top Positions")
    top = summary.get("top_positions", [])
    if top:
        top_df = (
            pd.DataFrame(top)
            .rename(columns={"symbol": "Symbol", "weight_pct": "Weight (%)"})
        )
        st.dataframe(top_df, width="stretch", hide_index=True)
    else:
        st.info("No position data available.")

    st.divider()

    # ── Row 4: Concentration alerts ───────────────────────────────────────
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
        # Every row in the flags list IS an alert — highlight all red.
        styled = flags_df.style.apply(
            lambda row: ["background-color: #ffcccc"] * len(row), axis=1
        )
        st.dataframe(styled, width="stretch", hide_index=True)
    else:
        st.success(f"No positions above the {threshold_pct}% concentration threshold.")

    st.divider()

    # ── Row 5: Positions breakdown ────────────────────────────────────────
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

        def _color_gain(col):
            return [
                "background-color: #e8f5e9" if not pd.isna(v) and v > 0
                else "background-color: #fdecea" if not pd.isna(v) and v < 0
                else ""
                for v in col
            ]

        tab_holdings, tab_income, tab_pnl, tab_accounts = st.tabs(
            ["Holdings", "Income", "P&L", "Accounts"]
        )

        # ── Holdings tab ──────────────────────────────────────────────────
        with tab_holdings:
            mv_col = "Live Market Value" if base["Live Market Value"].notna().any() else "CSV Market Value"
            cols = ["Symbol", "Security", "Sector", "Asset Class", "Weight (%)", "CSV Market Value", "Live Market Value"]
            st.dataframe(
                base[cols].sort_values("CSV Market Value", ascending=False),
                column_config={
                    "CSV Market Value":  st.column_config.NumberColumn("CSV Market Value ($)",  format="$%,.2f"),
                    "Live Market Value": st.column_config.NumberColumn("Live Market Value ($)", format="$%,.2f"),
                    "Weight (%)":        st.column_config.NumberColumn("Weight (%)",            format="%.2f%%"),
                },
                width="stretch", hide_index=True,
            )

        # ── Income tab ────────────────────────────────────────────────────
        with tab_income:
            inc_cols = ["Symbol", "Security", "Sector", "Current Price", "Div Yield (%)", "Annual Income", "Live Market Value"]
            inc_df = base[inc_cols].sort_values("Annual Income", ascending=False, na_position="last")
            st.dataframe(
                inc_df,
                column_config={
                    "Current Price":     st.column_config.NumberColumn("Current Price ($)",    format="$%.2f"),
                    "Div Yield (%)":     st.column_config.NumberColumn("Div Yield (%)",        format="%.2f%%"),
                    "Annual Income":     st.column_config.NumberColumn("Annual Income ($)",    format="$%,.2f"),
                    "Live Market Value": st.column_config.NumberColumn("Live Market Value ($)", format="$%,.2f"),
                },
                width="stretch", hide_index=True,
            )

        # ── P&L tab ───────────────────────────────────────────────────────
        with tab_pnl:
            pnl_cols = ["Symbol", "Security", "Cost Basis", "Unrealized Gain", "Unrealized Gain (%)", "Live Gain"]
            pnl_df = base[pnl_cols].sort_values("Unrealized Gain", ascending=True, na_position="last")
            _gain_col = "Live Gain" if pnl_df["Live Gain"].notna().any() else "Unrealized Gain"
            styled_pnl = pnl_df.style.apply(_color_gain, subset=[_gain_col])
            st.dataframe(
                styled_pnl,
                column_config={
                    "Cost Basis":           st.column_config.NumberColumn("Cost Basis ($)",         format="$%,.2f"),
                    "Unrealized Gain":      st.column_config.NumberColumn("Unrealized Gain ($)",    format="$%,.2f"),
                    "Unrealized Gain (%)":  st.column_config.NumberColumn("Unrealized Gain (%)",    format="%.2f%%"),
                    "Live Gain":            st.column_config.NumberColumn("Live Gain ($)",          format="$%,.2f"),
                },
                width="stretch", hide_index=True,
            )

        # ── Accounts tab ──────────────────────────────────────────────────
        with tab_accounts:
            acct_cols = ["Symbol", "Security", "Asset Class", "Registered", "Non-Reg", "Unclassified", "Accounts"]
            st.dataframe(
                base[acct_cols].sort_values("Registered", ascending=False, na_position="last"),
                column_config={
                    "Registered":   st.column_config.NumberColumn("Registered ($)",   format="$%,.2f"),
                    "Non-Reg":      st.column_config.NumberColumn("Non-Reg ($)",      format="$%,.2f"),
                    "Unclassified": st.column_config.NumberColumn("Unclassified ($)", format="$%,.2f"),
                },
                width="stretch", hide_index=True,
            )

    # ── Row 6: Portfolio Commentary ───────────────────────────────────────
    st.divider()
    st.subheader("Portfolio Commentary")

    _c_btn, _c_clr = st.columns([1, 6])
    with _c_btn:
        if st.button("Generate Commentary"):
            with st.spinner("Generating commentary — this may take up to a minute…"):
                st.session_state["commentary"] = _generate_commentary()
    with _c_clr:
        if st.session_state.get("commentary") and st.button("Clear"):
            st.session_state.pop("commentary", None)
            st.rerun()

    _commentary_result = st.session_state.get("commentary")
    if _commentary_result:
        if "error" in _commentary_result:
            st.error(_commentary_result["error"])
        else:
            st.markdown(_commentary_result["commentary"])
            st.caption(
                f"Provider: {_commentary_result.get('provider_used', '—')}  ·  "
                f"Prompt: {_commentary_result.get('prompt_length', 0):,} chars"
            )

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
