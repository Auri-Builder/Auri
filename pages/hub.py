"""
pages/hub.py — Auri Hub
-----------------------
Central landing page. Links to the three financial intelligence agents:
  1. Portfolio IA   — live prices, sector analysis, commentary
  2. Retirement     — projections, Monte Carlo, readiness score
  3. Wealth Builder — accumulation planning

No heavy data loading here — only lightweight status reads so the hub
loads instantly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st

from core._paths import (  # noqa: F401
    PROJECT_ROOT,
    _is_frozen,
    get_data_dir,
    get_active_profile,
    set_active_profile,
    list_profiles,
    create_profile,
    rename_profile,
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
    # If accounts.yaml is gone, invalidate cache immediately so hub shows clean state
    _accounts_file = get_data_dir() / "portfolio" / "accounts.yaml"
    if not _accounts_file.exists():
        try:
            from core.dashboard_cache import load_summary  # noqa: PLC0415
            load_summary.clear()
        except Exception:
            pass
        return {}
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


def _has_risk_profile() -> bool:
    """Return True if the investor questionnaire has been scored."""
    profile_path = get_data_dir() / "portfolio" / "profile.yaml"
    if not profile_path.exists():
        return False
    try:
        import yaml  # noqa: PLC0415
        prof = yaml.safe_load(profile_path.read_text()) or {}
        return (prof.get("derived") or {}).get("risk_score") is not None
    except Exception:
        return False


def _retirement_status() -> dict:
    """Read retirement profile + compute readiness score (quick deterministic run)."""
    profile_path = get_data_dir() / "retirement" / "retirement_profile.yaml"
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
            "score":          readiness["score"],
            "label":          readiness["label"],
            "portfolio":      readiness["total_portfolio"],
            "guaranteed":     readiness["guaranteed_annual"],
            "annual_spending": float(spending.get("annual_target", 0)),
            "has_spouse":     spouse_d is not None,
        }
    except Exception:
        return {}


def _wealth_status() -> dict:
    """Read wealth builder profile + run quick FI projection if data available."""
    profile_path = get_data_dir() / "wealth" / "wealth_profile.yaml"
    if not profile_path.exists():
        return {}
    try:
        import yaml
        wp   = yaml.safe_load(profile_path.read_text()) or {}
        fin  = wp.get("financials", {})
        pref = wp.get("preferences", {})
        nw   = wp.get("net_worth", {})

        current_age = int(fin.get("current_age", 0))
        ret_age     = int(fin.get("target_retirement_age", 0))
        if not current_age or not ret_age:
            return {}

        # Net worth from saved balance sheet — handle both legacy (flat assets list)
        # and new spouse-split format (primary/spouse/joint dicts + liabilities list)
        if "assets" in nw:
            # Legacy flat format
            total_assets = sum(float(a.get("value", 0)) for a in nw.get("assets", []))
            total_liab   = sum(float(l.get("balance", 0)) for l in nw.get("liabilities", []))
        else:
            # New spouse-split format: primary/spouse/joint dicts + liabilities list
            def _sum_dict(d: dict) -> float:
                return sum(float(v) for v in d.values() if isinstance(v, (int, float)))
            total_assets = (
                _sum_dict(nw.get("primary", {})) +
                _sum_dict(nw.get("spouse", {})) +
                _sum_dict(nw.get("joint", {}))
            )
            total_liab = sum(float(l.get("balance", 0)) for l in nw.get("liabilities", []))
        net_worth = total_assets - total_liab if total_assets else None

        # Quick FI projection using saved profile values
        fi_age = None
        shortfall = None
        balance_at_target = None
        fi_number_at_target = None
        try:
            from core.shared_profile import get_account_balances          # noqa: PLC0415
            from agents.ori_wb.projector import ProjectorInput, project    # noqa: PLC0415
            _acct      = get_account_balances()
            _portfolio = sum(_acct.values()) if _acct else 0.0
            _income    = float(fin.get("gross_income", 0))
            _sav_rate  = float(fin.get("savings_rate_pct", 20.0))
            if _income > 0 and current_age < ret_age:
                _proj = project(ProjectorInput(
                    current_age           = current_age,
                    current_savings       = _portfolio,
                    annual_income         = _income,
                    savings_rate_pct      = _sav_rate,
                    expected_return_pct   = float(fin.get("growth_rate_pct", 6.0)),
                    inflation_pct         = float(fin.get("inflation_pct", 2.5)),
                    target_retirement_age = ret_age,
                ))
                fi_age              = _proj.fi_age
                shortfall           = _proj.shortfall_at_target
                balance_at_target   = _proj.balance_at_target
                fi_number_at_target = _proj.fi_number_at_target
        except Exception:
            pass

        return {
            "current_age":        current_age,
            "ret_age":            ret_age,
            "yrs_to_ret":         ret_age - current_age,
            "risk":               pref.get("risk_tolerance", "moderate").capitalize(),
            "net_worth":          net_worth,
            "province":           pref.get("province", ""),
            "fi_age":             fi_age,
            "shortfall":          shortfall,
            "balance_at_target":  balance_at_target,
            "fi_number":          fi_number_at_target,
            "savings_rate":       float(fin.get("savings_rate_pct", 0)),
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


# ── Report builder ────────────────────────────────────────────────────────────

def _build_brief_html(
    portfolio: dict,
    wealth: dict,
    retirement: dict,
    commentary_path: Path,
) -> str:
    """Build a self-contained HTML financial brief for printing / sharing."""
    import json as _json
    from datetime import date as _date

    today = _date.today().strftime("%B %d, %Y")

    # ── Commentary ────────────────────────────────────────────────────────
    commentary_html = ""
    if commentary_path.exists():
        try:
            _c = _json.loads(commentary_path.read_text())
            _mode = "Challenge Analysis" if _c.get("mode") == "challenge" else "AI Commentary"
            _saved = _c.get("saved_at", "")[:10]
            _text  = _c.get("commentary", "").replace("<", "&lt;").replace(">", "&gt;")
            # Convert basic markdown bold/italic to HTML
            import re
            _text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _text)
            _text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         _text)
            _text = _text.replace("\n\n", "</p><p>").replace("\n", "<br>")
            commentary_html = f"""
            <h2>Portfolio {_mode}</h2>
            <p class="meta">Generated {_saved} · Provider: {_c.get("provider_used","—")}</p>
            <div class="commentary"><p>{_text}</p></div>"""
        except Exception:
            pass

    # ── Portfolio section ─────────────────────────────────────────────────
    port_rows = ""
    for p in portfolio.get("positions_summary", [])[:20]:
        sym  = p.get("symbol", "—")
        desc = (p.get("security_name") or p.get("description") or "")[:40]
        mv   = float(p.get("market_value") or 0)
        sect = p.get("sector") or p.get("asset_class") or ""
        port_rows += f"<tr><td>{sym}</td><td>{desc}</td><td>{sect}</td><td class='num'>{_fmt_cad(mv)}</td></tr>"

    _sw = portfolio.get("sector_weights_pct", {})
    sector_rows = "".join(
        f"<tr><td>{s}</td><td class='num'>{w:.1f}%</td></tr>"
        for s, w in sorted(_sw.items(), key=lambda x: -x[1])
    )

    # Account balances by owner
    _abo = portfolio.get("account_balance_by_owner", {})
    acct_rows = ""
    for owner, accts in _abo.items():
        for acct_type, bal in accts.items():
            acct_rows += f"<tr><td>{owner.capitalize()} — {acct_type}</td><td class='num'>{_fmt_cad(float(bal))}</td></tr>"

    # Unrealized gain if available
    _ug = portfolio.get("total_unrealized_gain")
    _ugp = portfolio.get("total_unrealized_gain_pct")
    ug_line = f"<tr><td>Unrealized Gain</td><td>{_fmt_cad(_ug)} ({_ugp:.1f}%)</td></tr>" if _ug is not None and _ugp is not None else ""

    # ── Wealth Builder section ─────────────────────────────────────────────
    fi_line = ""
    if wealth.get("fi_age"):
        delta = wealth["fi_age"] - wealth["ret_age"]
        fi_line = f"<tr><td>FI Age</td><td>{wealth['fi_age']} ({delta:+d} vs target {wealth['ret_age']})</td></tr>"
    elif wealth.get("shortfall") and wealth["shortfall"] > 0:
        fi_line = f"<tr><td>FI Age</td><td>Not reached by target · Shortfall {_fmt_cad(wealth['shortfall'])}</td></tr>"

    nw_line = f"<tr><td>Net Worth</td><td>{_fmt_cad(wealth['net_worth'])}</td></tr>" if wealth.get("net_worth") else ""

    # ── Retirement section ─────────────────────────────────────────────────
    ret_section = ""
    if retirement:
        ret_section = f"""
        <h2>Retirement Plan</h2>
        <table>
            <tr><td>Readiness Score</td><td>{retirement['score']:.0f} / 100 — {retirement['label']}</td></tr>
            <tr><td>Retirement Assets</td><td>{_fmt_cad(retirement['portfolio'])}</td></tr>
            <tr><td>Guaranteed Income</td><td>{_fmt_cad(retirement['guaranteed'])}/yr (CPP + OAS + pension)</td></tr>
            {'<tr><td>Annual Spending Target</td><td>' + _fmt_cad(retirement['annual_spending']) + '/yr</td></tr>' if retirement.get('annual_spending') else ''}
            {'<tr><td>Plan Type</td><td>Household (primary + spouse)</td></tr>' if retirement.get('has_spouse') else ''}
        </table>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Auri Financial Brief — {today}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 860px; margin: 40px auto; padding: 0 24px; color: #1a1a1a; }}
  h1   {{ font-size: 2em; margin-bottom: 4px; }}
  h2   {{ font-size: 1.2em; margin-top: 32px; border-bottom: 1px solid #ccc; padding-bottom: 4px; color: #1e3a5f; }}
  p.meta  {{ color: #666; font-size: 0.85em; margin: 0 0 12px; }}
  table   {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 0.92em; }}
  td, th  {{ padding: 6px 10px; border-bottom: 1px solid #eee; vertical-align: top; }}
  th      {{ background: #f0f4f8; font-weight: bold; text-align: left; }}
  td.num  {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .commentary {{ background: #f8f9fa; border-left: 3px solid #2563EB; padding: 12px 16px; font-size: 0.92em; line-height: 1.6; }}
  .disclaimer {{ font-size: 0.78em; color: #888; margin-top: 40px; border-top: 1px solid #eee; padding-top: 12px; }}
  @media print {{ body {{ margin: 20px; }} button {{ display: none; }} }}
</style>
</head>
<body>
<h1>Auri Financial Brief</h1>
<p class="meta">Prepared {today} · Confidential — for planning discussion only</p>

<h2>Portfolio Summary</h2>
<table>
  <tr><td>Total Value</td><td>{_fmt_cad(portfolio.get("total_market_value", 0))}</td></tr>
  <tr><td>Positions</td><td>{portfolio.get("position_count", 0)}</td></tr>
  {ug_line}
</table>
{'<h3 style="margin-top:16px;font-size:1em;">Account Balances by Owner</h3><table><tr><th>Account</th><th class=num>Balance</th></tr>' + acct_rows + '</table>' if acct_rows else ''}
{'<h3 style="margin-top:16px;font-size:1em;">Sector Weights</h3><table><tr><th>Sector</th><th class=num>Weight</th></tr>' + sector_rows + '</table>' if sector_rows else ''}
{'<h3 style="margin-top:16px;font-size:1em;">Holdings</h3><table><tr><th>Symbol</th><th>Security</th><th>Sector</th><th class=num>Market Value</th></tr>' + port_rows + '</table>' if port_rows else ''}

<h2>Wealth Builder</h2>
<table>
  <tr><td>Current Age → Target Retirement</td><td>{wealth.get('current_age')} → {wealth.get('ret_age')}</td></tr>
  <tr><td>Savings Rate</td><td>{wealth.get('savings_rate', 0):.0f}% of income</td></tr>
  <tr><td>Risk Tolerance</td><td>{wealth.get('risk', '—')}</td></tr>
  {fi_line}
  {nw_line}
</table>

{ret_section}

{commentary_html}

<div class="disclaimer">
  <strong>Disclaimer:</strong> All figures are estimates for planning and discussion purposes only.
  Tax calculations use simplified marginal rates and do not account for all deductions, credits, or
  personal circumstances. CPP and OAS projections are illustrative. Consult a registered financial
  advisor (CFPTM, PFPTM) and tax professional before acting on any information in this brief.
  Generated by Auri — local-first personal financial intelligence. Your data never leaves your machine.
</div>
</body>
</html>"""
    return html


# ── Main ─────────────────────────────────────────────────────────────────────

def _profile_selector() -> None:
    """Profile switcher — only shown in the frozen exe (multi-profile mode)."""
    if not _is_frozen():
        return

    profiles = list_profiles()
    profile_ids    = [p["id"]           for p in profiles]
    profile_labels = [p["display_name"] for p in profiles]

    current_id = get_active_profile()
    current_idx = profile_ids.index(current_id) if current_id in profile_ids else 0

    col_sel, col_new, col_rename = st.columns([3, 1, 1])

    with col_sel:
        chosen_label = st.selectbox(
            "Profile",
            options=profile_labels,
            index=current_idx,
            label_visibility="collapsed",
            key="profile_selector_box",
        )
        chosen_id = profile_ids[profile_labels.index(chosen_label)]
        if chosen_id != current_id:
            st.session_state["active_profile"] = chosen_id
            set_active_profile(chosen_id)
            # Clear all cached data so the new profile loads fresh
            from core.dashboard_cache import load_summary  # noqa: PLC0415
            load_summary.clear()
            for _key in ["price_data", "wb_opt_ran", "wb_proj_ran", "wb_reb_ran"]:
                st.session_state.pop(_key, None)
            st.rerun()

    with col_new:
        if st.button("+ New Profile", use_container_width=True):
            st.session_state["_new_profile_open"] = True

    with col_rename:
        if st.button("Rename", use_container_width=True):
            st.session_state["_rename_profile_open"] = True

    # ── New profile form ──────────────────────────────────────────────────
    if st.session_state.get("_new_profile_open"):
        with st.container(border=True):
            st.markdown("**Create new profile**")
            new_name = st.text_input("Profile name", key="new_profile_name_input",
                                     placeholder="e.g. Kids RESP, Dad's Portfolio")
            c1, c2 = st.columns(2)
            if c1.button("Create", key="new_profile_create_btn"):
                if new_name.strip():
                    new_id = create_profile(new_name.strip())
                    st.session_state["active_profile"] = new_id
                    set_active_profile(new_id)
                    st.session_state.pop("_new_profile_open", None)
                    st.session_state.pop("new_profile_name_input", None)
                    from core.dashboard_cache import load_summary  # noqa: PLC0415
                    load_summary.clear()
                    st.rerun()
                else:
                    st.error("Enter a name.")
            if c2.button("Cancel", key="new_profile_cancel_btn"):
                st.session_state.pop("_new_profile_open", None)
                st.rerun()

    # ── Rename form ───────────────────────────────────────────────────────
    if st.session_state.get("_rename_profile_open"):
        with st.container(border=True):
            st.markdown(f"**Rename '{chosen_label}'**")
            new_label = st.text_input("New name", key="rename_profile_input",
                                      value=chosen_label)
            c1, c2 = st.columns(2)
            if c1.button("Save", key="rename_profile_save_btn"):
                if new_label.strip():
                    rename_profile(chosen_id, new_label.strip())
                    st.session_state.pop("_rename_profile_open", None)
                    st.rerun()
                else:
                    st.error("Enter a name.")
            if c2.button("Cancel", key="rename_profile_cancel_btn"):
                st.session_state.pop("_rename_profile_open", None)
                st.rerun()


def main() -> None:
    # ── Header ────────────────────────────────────────────────────────────
    st.title("Auri")
    st.caption("Personal financial intelligence · local-first · your data never leaves your machine")

    # ── Profile selector (exe only) ───────────────────────────────────────
    _profile_selector()

    # ── Setup banner (only shown until all steps complete) ────────────────
    _profile_path  = get_data_dir() / "portfolio" / "profile.yaml"
    _targets_path  = get_data_dir() / "portfolio" / "targets.yaml"
    _accounts_path = get_data_dir() / "portfolio" / "accounts.yaml"
    _ret_path      = get_data_dir() / "retirement" / "retirement_profile.yaml"
    _ai_ok         = bool(_ai_status())

    _wealth_path  = get_data_dir() / "wealth" / "wealth_profile.yaml"
    _shared_path  = get_data_dir() / "shared_profile.yaml"
    _steps = [
        (_accounts_path.exists(), "Portfolio CSV uploaded",         "pages/wizard.py",           "Upload Wizard →"),
        (_ai_ok,                  "AI provider configured",         "pages/wizard.py",           "Configure in Upload Wizard →"),
        (_shared_path.exists(),   "Personal profile set up",        "pages/wizard.py",           "Set up in Wizard →"),
        (_wealth_path.exists(),   "Wealth Builder profile entered", "pages/wizard.py",           "Set up in Wizard →"),
        (_ret_path.exists(),      "Retirement profile entered",     "pages/7_Retirement.py",     "Retirement Planner →"),
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
    has_risk = _has_risk_profile()

    # ── Financial Snapshot ────────────────────────────────────────────────
    _has_portfolio = bool(portfolio)
    _has_wealth    = bool(wealth)
    _has_retirement = bool(retirement)

    if _has_portfolio or _has_wealth or _has_retirement:
        st.subheader("Financial Snapshot")
        _snap_cols = st.columns(3)

        with _snap_cols[0]:
            st.caption("**Portfolio**")
            if _has_portfolio:
                _tmv = portfolio.get("total_market_value", 0)
                _pr  = st.session_state.get("price_data")
                if _pr and not _pr.get("error") and _pr.get("price_data"):
                    _live = sum(
                        ((_pr["price_data"].get(str(p.get("symbol","")).upper(), {}).get("price") or 0)
                         * float(p.get("quantity") or 0))
                        or float(p.get("market_value") or 0)
                        for p in portfolio.get("positions_summary", [])
                    )
                    if _live > 0:
                        _tmv = _live
                st.markdown(f"**{_fmt_cad(_tmv)}** · {portfolio.get('position_count', 0)} positions")
                _sw = portfolio.get("sector_weights_pct", {})
                if _sw:
                    _top = max(_sw, key=_sw.get)
                    st.caption(f"Largest sector: {_top} ({_sw[_top]:.1f}%)")
            else:
                st.caption("No portfolio loaded")

        with _snap_cols[1]:
            st.caption("**Wealth Builder**")
            if _has_wealth:
                _fi_age   = wealth.get("fi_age")
                _shortfall = wealth.get("shortfall")
                _ret_age  = wealth.get("ret_age")
                st.markdown(f"Age **{wealth['current_age']}** → target **{_ret_age}** · {wealth['savings_rate']:.0f}% savings")
                if _fi_age:
                    _delta = _fi_age - _ret_age
                    _label = f"FI age **{_fi_age}** ({_delta:+d} vs target)"
                    st.markdown(_label)
                elif _shortfall and _shortfall > 0:
                    st.markdown(f"FI age not reached · shortfall **{_fmt_cad(_shortfall)}**")
                if wealth.get("net_worth") is not None:
                    st.caption(f"Net worth: {_fmt_cad(wealth['net_worth'])}")
            else:
                st.caption("No Wealth Builder profile")

        with _snap_cols[2]:
            st.caption("**Retirement**")
            if _has_retirement:
                _score = retirement["score"]
                _label = retirement["label"]
                st.markdown(f"Readiness **{_score:.0f}/100** · {_label}")
                st.caption(f"Guaranteed income: {_fmt_cad(retirement['guaranteed'])}/yr")
                if retirement.get("has_spouse"):
                    st.caption("Household projection")
            else:
                st.caption("No retirement profile yet")

        st.divider()

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
            if not portfolio:
                st.page_link("pages/wizard.py", label="Upload Portfolio CSV →")
            elif not has_risk:
                st.warning("Complete your investor profile to unlock the dashboard.")
                st.page_link("pages/profile.py", label="Investor Profile →")
            else:
                c_dash, c_anal = st.columns(2)
                c_dash.page_link("pages/1_Portfolio.py", label="Dashboard →")
                c_anal.page_link("pages/5_Analysis.py",  label="Analysis →")

    # ── Card 2: Wealth Builder ────────────────────────────────────────────
    with card2:
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
            st.page_link("pages/6_WealthBuilder.py", label="Wealth Builder →")

    # ── Card 3: Retirement Planner ────────────────────────────────────────
    with card3:
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
            st.page_link("pages/7_Retirement.py", label="Retirement Planner →")

    st.divider()

    # ── Financial Brief ───────────────────────────────────────────────────
    _brief_portfolio  = bool(portfolio)
    _brief_wealth     = bool(wealth)
    _brief_retirement = bool(retirement)
    _brief_commentary_path = get_data_dir() / "derived" / "commentary_latest.json"
    _brief_commentary = _brief_commentary_path.exists()
    _can_generate     = _brief_portfolio and _brief_wealth

    with st.expander("Financial Brief — advisor-ready summary", expanded=False):
        st.caption("Generate a one-page summary of your financial picture to share with your advisor.")

        # Pre-flight checklist
        _checks = [
            (_brief_portfolio,   "Portfolio loaded",            "Upload CSV in Wizard →",        "pages/wizard.py"),
            (_brief_wealth,      "Wealth Builder profile saved","Complete in Wealth Builder →",  "pages/6_WealthBuilder.py"),
            (_brief_retirement,  "Retirement plan (optional)",  "Set up in Retirement Planner →","pages/7_Retirement.py"),
            (_brief_commentary,  "AI commentary (optional)",    "Run in Analysis →",             "pages/5_Analysis.py"),
        ]
        for done, label, action, page in _checks:
            icon = "✅" if done else "⬜"
            if done:
                st.markdown(f"{icon} {label}")
            else:
                _bc1, _bc2 = st.columns([4, 1])
                _bc1.markdown(f"{icon} {label}")
                _bc2.page_link(page, label=action)

        st.divider()

        if not _can_generate:
            st.info("Load your portfolio CSV and save a Wealth Builder profile to generate the brief.")
        else:
            if st.button("Generate Financial Brief", type="primary", use_container_width=True):
                _html = _build_brief_html(portfolio, wealth, retirement, _brief_commentary_path)
                st.session_state["brief_html"] = _html

        if st.session_state.get("brief_html"):
            st.download_button(
                label="Download Brief (HTML — open in browser to print as PDF)",
                data=st.session_state["brief_html"],
                file_name=f"auri-financial-brief-{date.today()}.html",
                mime="text/html",
                use_container_width=True,
            )
            with st.expander("Preview"):
                st.components.v1.html(st.session_state["brief_html"], height=600, scrolling=True)

    st.divider()

    # ── Quick links strip ─────────────────────────────────────────────────
    st.caption("Tools")
    lc1, lc2, lc3, lc4 = st.columns(4)
    lc1.page_link("pages/wizard.py",    label="Upload Wizard")
    lc2.page_link("pages/snapshots.py", label="Snapshots")
    lc3.page_link("pages/health.py",    label="Health Check")

    ai_label = _ai_status()
    if ai_label:
        lc4.caption(f"AI: {ai_label}")
    else:
        lc4.page_link("pages/wizard.py", label="Configure AI →")


main()
