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
    st.set_page_config(page_title="ORI Portfolio Dashboard", layout="wide")
    st.title("ORI Portfolio Dashboard")
    st.caption("ORI_IA v0.1 · local only · no network calls")

    # Refresh clears the cache and immediately re-runs.
    if st.button("Refresh"):
        load_summary.clear()
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

        filtered = (
            pos_df[mask]
            .drop(columns=["reconciliation_delta"], errors="ignore")
            .rename(columns={
                "symbol":               "Symbol",
                "security_name":        "Security",
                "sector":               "Sector",
                "asset_class":          "Asset Class",
                "market_value":         "Market Value",
                "weight_pct":           "Weight (%)",
                "cost_basis":           "Cost Basis",
                "unrealized_gain":      "Unrealized Gain",
                "unrealized_gain_pct":  "Unrealized Gain (%)",
                "registered_value":     "Registered",
                "non_registered_value": "Non-Reg",
                "unclassified_value":   "Unclassified",
                "account_count":        "Accounts",
            })
            .sort_values("Market Value", ascending=False)
        )

        # ── P&L conditional formatting ─────────────────────────────────────
        # Soft green for gains, soft red for losses, blank for None / zero.
        # Applied to the "Unrealized Gain" column only — keeps the table clean.
        def _color_gain_col(col):
            return [
                "background-color: #e8f5e9" if not pd.isna(v) and v > 0
                else "background-color: #fdecea" if not pd.isna(v) and v < 0
                else ""
                for v in col
            ]

        styled = filtered.style.apply(_color_gain_col, subset=["Unrealized Gain"])

        st.dataframe(
            styled,
            column_config={
                "Market Value": st.column_config.NumberColumn(
                    "Market Value ($)", format="%.2f"
                ),
                "Weight (%)": st.column_config.NumberColumn(
                    "Weight (%)", format="%.2f%%"
                ),
                "Cost Basis": st.column_config.NumberColumn(
                    "Cost Basis ($)", format="%.2f"
                ),
                "Unrealized Gain": st.column_config.NumberColumn(
                    "Unrealized Gain ($)", format="%.2f"
                ),
                "Unrealized Gain (%)": st.column_config.NumberColumn(
                    "Unrealized Gain (%)", format="%.2f%%"
                ),
                "Registered": st.column_config.NumberColumn(
                    "Registered ($)", format="$%,.2f"
                ),
                "Non-Reg": st.column_config.NumberColumn(
                    "Non-Reg ($)", format="$%,.2f"
                ),
                "Unclassified": st.column_config.NumberColumn(
                    "Unclassified ($)", format="$%,.2f"
                ),
            },
            width="stretch",
            hide_index=True,
        )
        st.caption(f"Showing {len(filtered)} of {len(pos_df)} positions")

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
