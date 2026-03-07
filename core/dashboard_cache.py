"""
Shared data-loading helpers for Streamlit pages.

Centralised here so that Home.py and pages/5_Analysis.py share the same
@st.cache_data function objects — clearing the cache from one page clears it
for all pages.
"""

from pathlib import Path

import streamlit as st
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_CONFIG_PATH = PROJECT_ROOT / "dashboard.yaml"


def load_dashboard_config() -> dict:
    if not DASHBOARD_CONFIG_PATH.exists():
        return {}
    with DASHBOARD_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


@st.cache_data(show_spinner=False)
def load_summary() -> dict:
    dash_cfg = load_dashboard_config()

    if dash_cfg.get("dev_direct_call"):
        from core.job_runner import handle_portfolio_summary_v0  # noqa: PLC0415
        return handle_portfolio_summary_v0({})

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

    return result["output"]


def generate_commentary(mode: str = "standard") -> dict:
    dash_cfg = load_dashboard_config()
    params   = {"mode": mode}

    if dash_cfg.get("dev_direct_call"):
        from core.job_runner import handle_portfolio_commentary_v0  # noqa: PLC0415
        return handle_portfolio_commentary_v0(params)

    from core.oricore import submit_and_wait  # noqa: PLC0415

    result = submit_and_wait(
        "portfolio_commentary_v0",
        params,
        {"approval_required": False},
        timeout=180,
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


def load_suggested_targets() -> dict:
    """
    Fetch a risk-score-based target allocation suggestion.
    Not cached — called only when the user clicks "Suggest".
    """
    dash_cfg = load_dashboard_config()

    if dash_cfg.get("dev_direct_call"):
        from core.job_runner import handle_portfolio_suggest_targets_v0  # noqa: PLC0415
        return handle_portfolio_suggest_targets_v0({})

    from core.oricore import submit_and_wait  # noqa: PLC0415

    result = submit_and_wait(
        "portfolio_suggest_targets_v0",
        {},
        {"approval_required": False},
        timeout=15,
    )

    if result is None:
        return {"error": "Job timed out — is the job runner active?"}
    if result.get("status") != "ok":
        return {"error": result.get("error", "Job failed with unknown error")}

    return result["output"]


def save_targets(targets: dict, tolerance_pct: float = 5.0) -> dict:
    """Write accepted targets to targets.yaml. Not cached."""
    dash_cfg = load_dashboard_config()

    if dash_cfg.get("dev_direct_call"):
        from core.job_runner import handle_portfolio_save_targets_v0  # noqa: PLC0415
        return handle_portfolio_save_targets_v0({"targets": targets, "tolerance_pct": tolerance_pct})

    from core.oricore import submit_and_wait  # noqa: PLC0415

    result = submit_and_wait(
        "portfolio_save_targets_v0",
        {"targets": targets, "tolerance_pct": tolerance_pct},
        {"approval_required": False},
        timeout=15,
    )

    if result is None:
        return {"error": "Job timed out — is the job runner active?"}
    if result.get("status") != "ok":
        return {"error": result.get("error", "Job failed with unknown error")}

    return result["output"]


def fetch_benchmark(benchmark_symbol: str, from_date: str | None = None) -> dict:
    """Fetch benchmark ETF return. Not cached — called on explicit user request."""
    dash_cfg = load_dashboard_config()
    params   = {"benchmark_symbol": benchmark_symbol}
    if from_date:
        params["from_date"] = from_date

    if dash_cfg.get("dev_direct_call"):
        from core.job_runner import handle_portfolio_benchmark_v0  # noqa: PLC0415
        return handle_portfolio_benchmark_v0(params)

    from core.oricore import submit_and_wait  # noqa: PLC0415
    result = submit_and_wait(
        "portfolio_benchmark_v0", params, {"approval_required": False}, timeout=30,
    )
    if result is None:
        return {"error": "Benchmark job timed out — is the job runner active?"}
    if result.get("status") != "ok":
        return {"error": result.get("error", "Benchmark job failed.")}
    return result["output"]


@st.cache_data(show_spinner=False)
def load_allocation() -> dict:
    dash_cfg = load_dashboard_config()

    if dash_cfg.get("dev_direct_call"):
        from core.job_runner import handle_portfolio_allocation_v0  # noqa: PLC0415
        return handle_portfolio_allocation_v0({})

    from core.oricore import submit_and_wait  # noqa: PLC0415

    result = submit_and_wait(
        "portfolio_allocation_v0",
        {},
        {"approval_required": False},
        timeout=30,
    )

    if result is None:
        return {
            "error": (
                "Allocation job timed out — is the job runner active?\n\n"
                "Start it with:  python -m core.job_runner"
            )
        }
    if result.get("status") != "ok":
        return {"error": result.get("error", "Allocation job failed with unknown error")}

    return result["output"]
