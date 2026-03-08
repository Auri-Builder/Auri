"""
Home.py — Auri Hub
-------------------
Central landing page. Links to the three financial intelligence agents:
  1. Portfolio IA   — live prices, sector analysis, commentary
  2. Retirement     — projections, Monte Carlo, readiness score
  3. Wealth Builder — (coming soon) accumulation planning

No heavy data loading here — only lightweight status reads so the hub
loads instantly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent

st.set_page_config(
    page_title="Auri — Financial Intelligence",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_cad(v: float) -> str:
    return f"${v:,.0f}"


def _card(title: str, icon: str, lines: list[tuple[str, str]], link_page: str, link_label: str) -> None:
    """
    Render an agent card.

    lines : list of (label, value) tuples shown as metrics inside the card.
    """
    with st.container(border=True):
        st.markdown(f"### {icon} {title}")
        if lines:
            cols = st.columns(len(lines))
            for col, (lbl, val) in zip(cols, lines):
                col.metric(lbl, val)
        else:
            st.caption("No data yet — get started below.")
        st.page_link(link_page, label=link_label)


# ── Status reads (lightweight — no job runner, no spinner) ───────────────────

def _portfolio_status() -> dict:
    """Read cached summary if available; otherwise return empty."""
    try:
        from core.dashboard_cache import load_summary  # noqa: PLC0415
        # Only use cached result — never trigger a fresh load from the hub
        summary = load_summary.cache_data() if hasattr(load_summary, "cache_data") else None
        # Fallback: call directly (uses @st.cache_data, so fast on second load)
        if summary is None:
            summary = load_summary()
        if "error" in summary:
            return {}
        return summary
    except Exception:
        return {}


def _retirement_status() -> dict:
    """Read retirement profile + compute readiness score (quick deterministic run)."""
    profile_path = PROJECT_ROOT / "data" / "retirement" / "retirement_profile.yaml"
    if not profile_path.exists():
        return {}
    try:
        import yaml  # noqa: PLC0415
        rp       = yaml.safe_load(profile_path.read_text()) or {}
        household = rp.get("household", {})
        prim      = household.get("primary", {})
        spouse_d  = household.get("spouse")
        spending  = rp.get("spending", {})

        if not prim or not spending.get("annual_target"):
            return {}

        from agents.ori_rp.readiness import compute_readiness_score  # noqa: PLC0415
        from agents.ori_rp.cashflow import PersonProfile              # noqa: PLC0415

        spouse_pp = None
        if spouse_d:
            try:
                spouse_pp = PersonProfile(
                    current_age            = int(spouse_d.get("current_age", 65)),
                    rrsp_rrif_balance      = float(spouse_d.get("rrsp_rrif_balance", 0)),
                    tfsa_balance           = float(spouse_d.get("tfsa_balance", 0)),
                    non_registered_balance = float(spouse_d.get("non_registered_balance", 0)),
                    cpp_monthly_at_65      = float(spouse_d.get("cpp_monthly_at_65", 0)),
                    oas_monthly_at_65      = float(spouse_d.get("oas_monthly_at_65", 0)),
                    pension_monthly        = float(spouse_d.get("pension_monthly", 0)),
                    tfsa_room_remaining    = float(spouse_d.get("tfsa_room_remaining", 20_000)),
                    province               = prim.get("province", "ON"),
                )
            except Exception:
                pass

        readiness = compute_readiness_score(
            primary_age         = int(prim.get("current_age", 65)),
            rrsp_rrif_balance   = float(prim.get("rrsp_rrif_balance", 0)),
            tfsa_balance        = float(prim.get("tfsa_balance", 0)),
            non_reg_balance     = float(prim.get("non_registered_balance", 0)),
            tfsa_room_remaining = float(prim.get("tfsa_room_remaining", 0)),
            cpp_monthly_at_65   = float(prim.get("cpp_monthly_at_65", 0)),
            oas_monthly_at_65   = float(prim.get("oas_monthly_at_65", 0)),
            pension_monthly     = float(prim.get("pension_monthly", 0)),
            cpp_start_age       = int(prim.get("cpp_start_age", 65)),
            oas_start_age       = int(prim.get("oas_start_age", 65)),
            annual_spending     = float(spending.get("annual_target", 80_000)),
            province            = prim.get("province", "ON"),
            base_year           = date.today().year,
            spouse              = spouse_pp,
            sp_cpp_start_age    = int(spouse_d.get("cpp_start_age", 65)) if spouse_d else 0,
            sp_oas_start_age    = int(spouse_d.get("oas_start_age", 65)) if spouse_d else 0,
        )
        return {
            "score":       readiness["score"],
            "label":       readiness["label"],
            "portfolio":   readiness["total_portfolio"],
            "guaranteed":  readiness["guaranteed_annual"],
            "has_spouse":  spouse_d is not None,
        }
    except Exception:
        return {}


def _wealth_status() -> dict:
    """Read wealth builder profile if available."""
    profile_path = PROJECT_ROOT / "data" / "wealth" / "wealth_profile.yaml"
    if not profile_path.exists():
        return {}
    try:
        import yaml
        wp  = yaml.safe_load(profile_path.read_text()) or {}
        fin = wp.get("financials", {})
        pref = wp.get("preferences", {})
        nw   = wp.get("net_worth", {})

        current_age = int(fin.get("current_age", 0))
        ret_age     = int(fin.get("target_retirement_age", 0))
        if not current_age or not ret_age:
            return {}

        # Net worth from saved balance sheet
        total_assets = sum(float(a.get("value", 0)) for a in nw.get("assets", []))
        total_liab   = sum(float(l.get("balance", 0)) for l in nw.get("liabilities", []))
        net_worth    = total_assets - total_liab if total_assets else None

        return {
            "current_age":    current_age,
            "ret_age":        ret_age,
            "yrs_to_ret":     ret_age - current_age,
            "risk":           pref.get("risk_tolerance", "moderate").capitalize(),
            "net_worth":      net_worth,
            "province":       pref.get("province", ""),
        }
    except Exception:
        return {}


def _ai_status() -> str:
    """Return short label for configured AI provider, or empty string."""
    try:
        from agents.ai_provider import is_configured, _load_config  # noqa: PLC0415
        if not is_configured():
            return ""
        cfg = _load_config()
        return cfg.get("ai_provider", "").capitalize()
    except Exception:
        return ""


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── Header ────────────────────────────────────────────────────────────
    st.title("Auri")
    st.caption("Personal financial intelligence · local-first · your data never leaves your machine")

    # ── Setup banner (only shown until all steps complete) ────────────────
    _profile_path  = PROJECT_ROOT / "data" / "portfolio" / "profile.yaml"
    _targets_path  = PROJECT_ROOT / "data" / "portfolio" / "targets.yaml"
    _accounts_path = PROJECT_ROOT / "data" / "portfolio" / "accounts.yaml"
    _ret_path      = PROJECT_ROOT / "data" / "retirement" / "retirement_profile.yaml"
    _ai_ok         = bool(_ai_status())

    _wealth_path = PROJECT_ROOT / "data" / "wealth" / "wealth_profile.yaml"
    _steps = [
        (_accounts_path.exists(), "Portfolio CSV uploaded",         "pages/wizard.py",          "Upload Wizard →"),
        (_ai_ok,                  "AI provider configured",         "pages/wizard.py",          "Configure in Upload Wizard →"),
        (_ret_path.exists(),      "Retirement profile entered",     "pages/6_Retirement.py",    "Retirement Planner →"),
        (_wealth_path.exists(),   "Wealth Builder profile entered", "pages/7_WealthBuilder.py", "Wealth Builder →"),
    ]
    _incomplete = [s for s in _steps if not s[0]]
    if _incomplete:
        with st.expander(
            f"Getting started — {len(_incomplete)} step{'s' if len(_incomplete) != 1 else ''} remaining",
            expanded=True,
        ):
            for done, label, page, link_text in _steps:
                icon = "✅" if done else "⬜"
                if done:
                    st.markdown(f"{icon} {label}")
                else:
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f"{icon} **{label}**")
                    c2.page_link(page, label=link_text)

    st.divider()

    # ── Agent cards ───────────────────────────────────────────────────────
    portfolio = _portfolio_status()
    retirement = _retirement_status()
    wealth = _wealth_status()

    card1, card2, card3 = st.columns(3, gap="large")

    # ── Card 1: Portfolio IA ──────────────────────────────────────────────
    with card1:
        with st.container(border=True):
            st.markdown("### Portfolio Intelligence")
            st.caption("Live prices · sector analysis · AI commentary · stress testing")
            st.divider()
            if portfolio:
                _price_result = st.session_state.get("price_data")
                _tmv = portfolio.get("total_market_value", 0)
                if _price_result and "error" not in _price_result and _price_result.get("price_data"):
                    _pd_map = _price_result["price_data"]
                    _live = sum(
                        ((_pd_map.get(str(p.get("symbol","")).upper(), {}).get("price") or 0)
                         * float(p.get("quantity") or 0))
                        or float(p.get("market_value") or 0)
                        for p in portfolio.get("positions_summary", [])
                    )
                    if _live > 0:
                        _tmv = _live

                c1, c2 = st.columns(2)
                c1.metric("Portfolio Value",  _fmt_cad(_tmv) if _tmv else "—")
                c2.metric("Positions",        portfolio.get("position_count", "—"))

                _sector_wts = portfolio.get("sector_weights_pct", {})
                if _sector_wts:
                    _top_sector = max(_sector_wts, key=_sector_wts.get)
                    st.caption(f"Largest sector: **{_top_sector}** ({_sector_wts[_top_sector]:.1f}%)")
                    if _price_result and "error" not in _price_result:
                        fc = _price_result.get("fetched_count", 0)
                        sc = _price_result.get("stale_count", 0)
                        fa = _price_result.get("fetched_at", "")
                        st.caption(f"Prices: {fc} live, {sc} stale · {fa}")
            else:
                st.info("No portfolio loaded yet.")

            st.divider()
            c_dash, c_anal = st.columns(2)
            c_dash.page_link("pages/1_Portfolio.py",  label="Dashboard →")
            c_anal.page_link("pages/5_Analysis.py",   label="Analysis →")

    # ── Card 2: Retirement Planner ────────────────────────────────────────
    with card2:
        with st.container(border=True):
            st.markdown("### Retirement Planner")
            st.caption("Projections · Monte Carlo · CPP/OAS timing · tax efficiency")
            st.divider()
            if retirement:
                score = retirement["score"]
                label = retirement["label"]
                colour = {"Excellent": "normal", "Good": "normal"}.get(label, "inverse")
                r1, r2 = st.columns(2)
                r1.metric("Readiness Score", f"{score:.0f} / 100",
                          delta=label, delta_color=colour)
                r2.metric("Retirement Assets", _fmt_cad(retirement["portfolio"]))
                if retirement.get("has_spouse"):
                    st.caption("Household projection (primary + spouse)")
                st.caption(f"Guaranteed income: {_fmt_cad(retirement['guaranteed'])}/yr")
            else:
                st.info("No retirement profile yet.")

            st.divider()
            st.page_link("pages/6_Retirement.py", label="Retirement Planner →")

    # ── Card 3: Wealth Builder ────────────────────────────────────────────
    with card3:
        with st.container(border=True):
            st.markdown("### Wealth Builder")
            st.caption("RRSP/TFSA optimizer · FI projector · allocation · net worth")
            st.divider()
            if wealth:
                w1, w2 = st.columns(2)
                w1.metric("Years to Retirement", wealth["yrs_to_ret"])
                if wealth["net_worth"] is not None:
                    w2.metric("Net Worth", _fmt_cad(wealth["net_worth"]))
                else:
                    w2.metric("Risk Tolerance", wealth["risk"])
                st.caption(f"Age {wealth['current_age']} → {wealth['ret_age']} · {wealth['risk']} · {wealth['province']}")
            else:
                st.info("No profile yet — get started below.")
            st.divider()
            st.page_link("pages/7_WealthBuilder.py", label="Wealth Builder →")

    st.divider()

    # ── Quick links strip ─────────────────────────────────────────────────
    st.caption("Tools")
    lc1, lc2, lc3, lc4 = st.columns(4)
    lc1.page_link("pages/wizard.py",       label="Upload Wizard")
    lc2.page_link("pages/snapshots.py",    label="Snapshots")
    lc3.page_link("pages/health.py",       label="Health Check")

    ai_label = _ai_status()
    if ai_label:
        lc4.caption(f"AI: {ai_label}")
    else:
        lc4.page_link("pages/wizard.py", label="Configure AI →")


if __name__ == "__main__":
    main()
else:
    main()
