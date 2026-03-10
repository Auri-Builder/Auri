"""
ORI Snapshots — pages/snapshots.py

Create point-in-time portfolio snapshots and compare them to track drift.

Snapshots are stored in data/derived/ (gitignored).
Only aggregate fields are persisted — no row-level holdings data.

Calls portfolio_snapshot_v0 and portfolio_compare_v0 job actions via
the same dev_direct_call / governed routing used by the main dashboard.
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
from core._paths import PROJECT_ROOT, DATA_ROOT  # noqa: F401
DERIVED_DIR = DATA_ROOT / "data" / "derived"
DASHBOARD_CONFIG_PATH = PROJECT_ROOT / "dashboard.yaml"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_dashboard_config() -> dict:
    if not DASHBOARD_CONFIG_PATH.exists():
        return {}
    with DASHBOARD_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _call_action(action: str, params: dict) -> dict:
    """
    Route a job action through dev_direct_call or the governed job queue,
    matching the pattern used by the main dashboard.
    """
    dash_cfg = _load_dashboard_config()
    if dash_cfg.get("dev_direct_call"):
        from core.job_runner import ACTION_HANDLERS
        handler = ACTION_HANDLERS.get(action)
        if handler is None:
            return {"error": f"Action '{action}' not registered in ACTION_HANDLERS"}
        return handler(params)
    else:
        from core.oricore import submit_and_wait
        result = submit_and_wait(
            action, params, {"approval_required": False}, timeout=30
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
        return result["output"]


def _list_snapshots() -> list[str]:
    """Return snapshot filenames sorted newest-first."""
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(
        [f.name for f in DERIVED_DIR.glob("*.json")],
        reverse=True,
    )


def _load_history() -> pd.DataFrame:
    """
    Read every snapshot JSON in data/derived/ and return a tidy DataFrame
    sorted chronologically.  Rows with missing total_market_value are skipped.
    When multiple snapshots share a date the one with the latest timestamp wins.
    """
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for f in DERIVED_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        mv = data.get("total_market_value")
        if mv is None:
            continue
        records.append({
            "date":             data.get("date") or f.name[:10],
            "timestamp":        data.get("timestamp", ""),
            "label":            data.get("label", ""),
            "Market Value":     mv,
            "Unrealized Gain":  data.get("total_unrealized_gain"),
            "Gain %":           data.get("total_unrealized_gain_pct"),
            "Positions":        data.get("position_count"),
            "sector_weights":   data.get("sector_weights_pct", {}),
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    # Keep the latest-timestamped snapshot per calendar date
    df = (
        df.sort_values(["date", "timestamp"])
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return df


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("Snapshots")
st.caption(
    "Point-in-time portfolio snapshots · aggregates only · "
    "stored in data/derived/ · local only · no network calls"
)

# ── Portfolio History ────────────────────────────────────────────────────────

st.subheader("Portfolio History")

_hist = _load_history()

if _hist.empty:
    st.info("No snapshots yet — create your first one below.")
else:
    # ── Summary metrics (first vs latest) ─────────────────────────────────
    _first = _hist.iloc[0]
    _last  = _hist.iloc[-1]
    _span  = len(_hist)

    _delta_mv  = _last["Market Value"] - _first["Market Value"]
    _delta_pct = _delta_mv / _first["Market Value"] * 100 if _first["Market Value"] else None

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Snapshots", _span)
    m2.metric(
        "First snapshot",
        f"${_first['Market Value']:,.0f}",
        help=str(_first["date"].date()),
    )
    m3.metric(
        "Latest snapshot",
        f"${_last['Market Value']:,.0f}",
        delta=f"{'+' if _delta_mv >= 0 else ''}${_delta_mv:,.0f}",
        delta_color="normal",
        help=str(_last["date"].date()),
    )
    if _delta_pct is not None:
        m4.metric(
            "Total return",
            f"{'+' if _delta_pct >= 0 else ''}{_delta_pct:.1f}%",
            delta_color="normal",
        )

    # ── Market value line chart ────────────────────────────────────────────
    _chart_df = _hist.set_index("date")[["Market Value"]]
    st.line_chart(_chart_df, use_container_width=True)

    # ── Unrealized gain overlay (when available) ───────────────────────────
    _gain_rows = _hist.dropna(subset=["Unrealized Gain"])
    if not _gain_rows.empty and len(_gain_rows) >= 2:
        with st.expander("Unrealized gain over time"):
            _gain_df = _gain_rows.set_index("date")[["Unrealized Gain"]]
            st.line_chart(_gain_df, use_container_width=True)

    # ── Sector weight drift table (first vs last) ──────────────────────────
    _sec_first = _first.get("sector_weights") or {}
    _sec_last  = _last.get("sector_weights") or {}

    if _sec_first and _sec_last and _span >= 2:
        with st.expander("Sector weight drift  (first → latest snapshot)"):
            all_secs = sorted(set(_sec_first) | set(_sec_last))
            drift_rows = []
            for sec in all_secs:
                wa = _sec_first.get(sec, 0.0) or 0.0
                wb = _sec_last.get(sec, 0.0) or 0.0
                drift_rows.append({
                    "Sector":    sec,
                    f"{str(_first['date'].date())} %": round(wa, 2),
                    f"{str(_last['date'].date())} %":  round(wb, 2),
                    "Δ pp":      round(wb - wa, 2),
                })
            drift_df = pd.DataFrame(drift_rows).sort_values("Δ pp", ascending=False)

            def _colour_drift(val):
                if val > 2:
                    return "color: #c62828"
                if val < -2:
                    return "color: #1565c0"
                return ""

            st.dataframe(
                drift_df.style.map(_colour_drift, subset=["Δ pp"]),
                use_container_width=True,
                hide_index=True,
            )

    # ── Snapshot log table ─────────────────────────────────────────────────
    with st.expander("Snapshot log"):
        log_cols = ["date", "label", "Market Value", "Unrealized Gain", "Gain %", "Positions"]
        log_df = _hist[log_cols].copy()
        log_df["date"] = log_df["date"].dt.date
        st.dataframe(
            log_df,
            column_config={
                "date":            st.column_config.DateColumn("Date"),
                "label":           st.column_config.TextColumn("Label"),
                "Market Value":    st.column_config.NumberColumn("Market Value", format="dollar"),
                "Unrealized Gain": st.column_config.NumberColumn("Unrealized Gain", format="dollar"),
                "Gain %":          st.column_config.NumberColumn("Gain %", format="%.2f%%"),
                "Positions":       st.column_config.NumberColumn("Positions"),
            },
            use_container_width=True,
            hide_index=True,
        )

st.divider()

# ── Create Snapshot ─────────────────────────────────────────────────────────

st.subheader("Create Snapshot")

col1, col2 = st.columns(2)
with col1:
    snap_label = st.text_input(
        "Label",
        value="snapshot",
        help="Embedded in the filename. Only letters, numbers, hyphens, underscores.",
    )
with col2:
    snap_date = st.date_input("Date", value=date.today())

if st.button("Create Snapshot", type="primary"):
    with st.spinner("Running portfolio summary…"):
        result = _call_action(
            "portfolio_snapshot_v0",
            {"label": snap_label, "date": snap_date.strftime("%Y-%m-%d")},
        )

    if "error" in result:
        st.error(result["error"])
    else:
        snap_file = result.get("snapshot_file", "")
        summary = result.get("summary", {})
        st.success(f"Saved: {snap_file}")

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Market Value", f"${summary.get('total_market_value', 0):,.2f}")
        c2.metric("Positions", summary.get("position_count", 0))
        c3.metric("Unique Symbols", summary.get("unique_symbols", 0))

st.divider()

# ── Compare Snapshots ────────────────────────────────────────────────────────

st.subheader("Compare Snapshots")

snapshots = _list_snapshots()

if len(snapshots) < 2:
    st.info(
        f"Need at least 2 snapshots to compare — "
        f"currently {len(snapshots)} in data/derived/."
    )
else:
    col1, col2 = st.columns(2)
    with col1:
        snap_a_name = st.selectbox(
            "Snapshot A (older / baseline)",
            options=snapshots,
            index=min(1, len(snapshots) - 1),
        )
    with col2:
        snap_b_name = st.selectbox(
            "Snapshot B (newer)",
            options=snapshots,
            index=0,
        )

    if st.button("Compare", type="primary"):
        if snap_a_name == snap_b_name:
            st.warning("Select two different snapshots to compare.")
        else:
            with st.spinner("Computing diff…"):
                result = _call_action(
                    "portfolio_compare_v0",
                    {
                        "snapshot_a": f"data/derived/{snap_a_name}",
                        "snapshot_b": f"data/derived/{snap_b_name}",
                    },
                )

            if "error" in result:
                st.error(result["error"])
            else:
                mv_a     = result.get("total_market_value_a", 0)
                mv_b     = result.get("total_market_value_b", 0)
                delta_mv = result.get("delta_total_market_value", 0)
                delta_pct = result.get("delta_total_market_value_pct")
                delta_ug  = result.get("delta_unrealized_gain")

                # ── Portfolio value summary ────────────────────────────────
                c1, c2, c3 = st.columns(3)
                c1.metric("Value (A)",  f"${mv_a:,.0f}")
                c2.metric("Value (B)",  f"${mv_b:,.0f}")
                sign = "+" if delta_mv >= 0 else ""
                pct_label = f"({sign}{delta_pct:.2f}%)" if delta_pct is not None else ""
                c3.metric(
                    "Change",
                    f"{sign}${delta_mv:,.0f}",
                    delta=pct_label if pct_label else None,
                    delta_color="normal",
                )

                if delta_ug is not None:
                    ug_sign = "+" if delta_ug >= 0 else ""
                    st.caption(f"Unrealized gain change: {ug_sign}${delta_ug:,.2f}")

                st.divider()

                # ── Positions added / removed ──────────────────────────────
                added   = result.get("positions_added", [])
                removed = result.get("positions_removed", [])
                if added or removed:
                    st.subheader("Positions Added / Removed")
                    p1, p2 = st.columns(2)
                    with p1:
                        if added:
                            st.success(f"**Added ({len(added)}):** {', '.join(added)}")
                        else:
                            st.info("No new positions.")
                    with p2:
                        if removed:
                            st.warning(f"**Removed ({len(removed)}):** {', '.join(removed)}")
                        else:
                            st.info("No closed positions.")
                    st.divider()

                # ── Top position weight changes ────────────────────────────
                st.subheader("Top Position Weight Changes")
                top_changes = result.get("top_position_changes", [])

                def _colour_delta(val):
                    if val is None:
                        return ""
                    return "color: green" if val > 0 else "color: red" if val < 0 else ""

                if top_changes:
                    top_df = pd.DataFrame(top_changes).rename(columns={
                        "symbol":       "Symbol",
                        "weight_pct_a": "Weight % (A)",
                        "weight_pct_b": "Weight % (B)",
                        "delta_pct":    "Delta %",
                    })
                    styled_top = top_df.style.map(_colour_delta, subset=["Delta %"])
                    st.dataframe(styled_top, use_container_width=True, hide_index=True)
                else:
                    st.info("No top-position data in snapshots.")

                st.divider()

                # ── Sector drift ───────────────────────────────────────────
                st.subheader("Sector Drift")
                sector_drift = result.get("sector_drift", [])
                if sector_drift:
                    sec_df = pd.DataFrame(sector_drift).rename(columns={
                        "sector":       "Sector",
                        "weight_pct_a": "Weight % (A)",
                        "weight_pct_b": "Weight % (B)",
                        "delta_pct":    "Delta %",
                    })
                    styled_sec = sec_df.style.map(_colour_delta, subset=["Delta %"])
                    st.dataframe(styled_sec, use_container_width=True, hide_index=True)
                else:
                    st.info("No sector data in snapshots.")

                st.divider()

                # ── Concentration changes ──────────────────────────────────
                st.subheader("Concentration Changes")
                conc    = result.get("concentration_changes", {})
                newly   = conc.get("newly_flagged", [])
                dropped = conc.get("dropped_below", [])
                if newly:
                    st.warning(f"Newly above threshold: {', '.join(newly)}")
                if dropped:
                    st.success(f"Dropped below threshold: {', '.join(dropped)}")
                if not newly and not dropped:
                    st.info("No concentration changes between snapshots.")

# ── Footer ────────────────────────────────────────────────────────────────────

st.divider()
if st.button("Go to Hub"):
        st.switch_page("pages/hub.py")
