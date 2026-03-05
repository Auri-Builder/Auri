"""
ORI Snapshots — pages/snapshots.py

Create point-in-time portfolio snapshots and compare them to track drift.

Snapshots are stored in data/derived/ (gitignored).
Only aggregate fields are persisted — no row-level holdings data.

Calls portfolio_snapshot_v0 and portfolio_compare_v0 job actions via
the same dev_direct_call / governed routing used by the main dashboard.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DERIVED_DIR = PROJECT_ROOT / "data" / "derived"
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

# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Auri · Snapshots", layout="wide")
st.title("Snapshots")
st.caption(
    "Point-in-time portfolio snapshots · aggregates only · "
    "stored in data/derived/ · local only · no network calls"
)

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
                delta_mv = result.get("delta_total_market_value", 0)
                sign = "+" if delta_mv >= 0 else ""
                st.metric(
                    "Total Market Value Change",
                    f"{sign}${delta_mv:,.2f}",
                )

                st.divider()

                # Top position changes
                st.subheader("Top Position Changes")
                top_changes = result.get("top_position_changes", [])
                if top_changes:
                    top_df = pd.DataFrame(top_changes).rename(columns={
                        "symbol":       "Symbol",
                        "weight_pct_a": "Weight % (A)",
                        "weight_pct_b": "Weight % (B)",
                        "delta_pct":    "Delta %",
                    })

                    def _colour_delta(val):
                        if val is None:
                            return ""
                        return (
                            "color: green" if val > 0
                            else "color: red" if val < 0
                            else ""
                        )

                    styled_top = top_df.style.map(_colour_delta, subset=["Delta %"])
                    st.dataframe(styled_top, width="stretch", hide_index=True)
                else:
                    st.info("No top-position data in snapshots.")

                st.divider()

                # Sector drift
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
                    st.dataframe(styled_sec, width="stretch", hide_index=True)
                else:
                    st.info("No sector data in snapshots.")

                st.divider()

                # Concentration changes
                st.subheader("Concentration Changes")
                conc = result.get("concentration_changes", {})
                newly = conc.get("newly_flagged", [])
                dropped = conc.get("dropped_below", [])
                if newly:
                    st.warning(f"Newly above threshold: {', '.join(newly)}")
                if dropped:
                    st.success(f"Dropped below threshold: {', '.join(dropped)}")
                if not newly and not dropped:
                    st.info("No concentration changes between snapshots.")

# ── Footer ────────────────────────────────────────────────────────────────────

st.divider()
st.page_link("app.py", label="Go to Dashboard")
