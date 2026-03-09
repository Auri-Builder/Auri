"""
ORI Personal — Investor Profile page (pages/profile.py)

Three tabs:
  Score          — risk score metrics, run scorer, per-question breakdown
  Questionnaire  — answer the 7 risk questions directly in the UI
  Approach       — edit investment goals, constraints, and tax notes

All writes go to gitignored files (answers.yaml, profile.yaml).
No raw answer values are displayed on the Score tab — only derived aggregates.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_DIR = PROJECT_ROOT / "data" / "portfolio"
DASHBOARD_CONFIG_PATH = PROJECT_ROOT / "dashboard.yaml"

PROFILE_PATH   = PORTFOLIO_DIR / "profile.yaml"
QUESTIONS_PATH = PORTFOLIO_DIR / "questions.yaml"
ANSWERS_PATH   = PORTFOLIO_DIR / "answers.yaml"

# ---------------------------------------------------------------------------
# Option labels (human-readable display for raw option keys)
# ---------------------------------------------------------------------------

_OPTION_LABELS: dict[str, str] = {
    "capital_preservation": "Capital Preservation — protect what you have",
    "income":               "Income — regular income stream",
    "balanced":             "Balanced — blend of income and growth",
    "growth":               "Growth — long-term appreciation",
    "aggressive_growth":    "Aggressive Growth — maximum long-term appreciation",
    "less_than_2_years":    "Less than 2 years",
    "2_to_5_years":         "2–5 years",
    "5_to_10_years":        "5–10 years",
    "10_to_20_years":       "10–20 years",
    "more_than_20_years":   "More than 20 years",
    "sell_everything":      "Sell everything — cannot tolerate that level of loss",
    "sell_some":            "Sell some — reduce exposure significantly",
    "hold":                 "Hold — stay the course and wait for recovery",
    "buy_more":             "Buy more — opportunistically add at lower prices",
    "not_important":        "Not important — spend it all, legacy not a priority",
    "somewhat_important":   "Somewhat important — nice to have if possible",
    "important":            "Important — a meaningful transfer is a goal",
    "very_important":       "Very important — wealth transfer is a primary objective",
}

_LABEL_COLOUR = {
    "conservative":            "#1565c0",
    "moderately_conservative": "#0277bd",
    "balanced":                "#2e7d32",
    "growth":                  "#f57f17",
    "aggressive":              "#b71c1c",
}

_LABEL_DISPLAY = {
    "conservative":            "Conservative",
    "moderately_conservative": "Moderately Conservative",
    "balanced":                "Balanced",
    "growth":                  "Growth",
    "aggressive":              "Aggressive",
}


# ---------------------------------------------------------------------------
# Helpers — load / save
# ---------------------------------------------------------------------------

def _load_dashboard_config() -> dict:
    if not DASHBOARD_CONFIG_PATH.exists():
        return {}
    with DASHBOARD_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _load_profile() -> dict:
    if not PROFILE_PATH.exists():
        return {}
    with PROFILE_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_questions() -> list[dict]:
    if not QUESTIONS_PATH.exists():
        return []
    with QUESTIONS_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("questions", [])


def _load_answers() -> dict:
    """Return {question_id: {answered, value}} from answers.yaml."""
    if not ANSWERS_PATH.exists():
        return {}
    with ANSWERS_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {
        a["question_id"]: {"answered": a.get("answered", False), "value": a.get("value")}
        for a in data.get("answers", [])
        if "question_id" in a
    }


def _save_answers(questions: list[dict], form_values: dict[str, object]) -> None:
    """Write form_values back to answers.yaml, preserving version/owner."""
    existing_data: dict = {}
    if ANSWERS_PATH.exists():
        with ANSWERS_PATH.open("r", encoding="utf-8") as fh:
            existing_data = yaml.safe_load(fh) or {}

    answers_out = []
    for q in questions:
        qid = q["question_id"]
        val = form_values.get(qid)
        answered = val is not None
        answers_out.append({"question_id": qid, "answered": answered, "value": val})

    out = {
        "version": existing_data.get("version", "1.0"),
        "owner":   existing_data.get("owner", "jeff"),
        "answers": answers_out,
    }
    ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ANSWERS_PATH.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(out, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _save_profile(updated: dict) -> None:
    """Merge updated fields into profile.yaml (preserves derived block)."""
    existing: dict = _load_profile()
    existing.update(updated)
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROFILE_PATH.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(existing, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _run_profile_score() -> dict:
    dash_cfg = _load_dashboard_config()
    if dash_cfg.get("dev_direct_call"):
        from core.job_runner import handle_portfolio_profile_v0  # noqa: PLC0415
        return handle_portfolio_profile_v0({})
    from core.oricore import submit_and_wait  # noqa: PLC0415
    result = submit_and_wait(
        "portfolio_profile_v0", {}, {"approval_required": False}, timeout=30
    )
    if result is None:
        return {"error": "Profile scoring job timed out."}
    if result.get("status") != "ok":
        return {"error": result.get("error", "Profile job failed.")}
    return result["output"]


def _fmt_pct(v: float | None) -> str:
    return f"{v:.1f}%" if v is not None else "—"


def _fmt_score(v: float | None) -> str:
    return f"{v:.1f}" if v is not None else "—"


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Auri · Investor Profile", layout="wide")
from core.ui import hide_sidebar_nav; hide_sidebar_nav()  # noqa: E402
st.title("Investor Profile")

# Breadcrumb
_crumb_pages = [("Hub","Home.py"),("Portfolio","pages/1_Portfolio.py"),("Investor Profile",None)]
st.caption("  ›  ".join(f"**{l}**" if p is None else f"[{l}]({p})" for l, p in _crumb_pages))

questions    = _load_questions()
profile      = _load_profile()
derived      = profile.get("derived", {})
score_result = st.session_state.get("profile_score_result")

_profile_complete = derived.get("risk_score") is not None
_has_answers      = ANSWERS_PATH.exists()

# ── Onboarding banner ─────────────────────────────────────────────────────────
if not _has_answers:
    st.info(
        "**Welcome — let's build your investor profile.**  \n"
        "Answer the questions in the **Questionnaire** tab below. "
        "It takes about 2 minutes and tells us how to calibrate your portfolio analysis.  \n"
        "Your answers are saved locally and never leave your computer."
    )

# ── Tabs — Questionnaire first for new users, Score first once complete ───────
if _profile_complete:
    tab_score, tab_q, tab_approach = st.tabs(["Score", "Questionnaire", "Investment Approach"])
else:
    tab_q, tab_score, tab_approach = st.tabs(["Questionnaire", "Score", "Investment Approach"])


# ===========================================================================
# Tab 1 — Score
# ===========================================================================
with tab_score:
    if score_result and "error" not in score_result:
        risk_score       = score_result.get("risk_score")
        risk_label       = score_result.get("risk_label")
        completeness_pct = score_result.get("completeness_pct", 0.0)
        answered_count   = score_result.get("answered_count", 0)
        max_dd           = score_result.get("max_drawdown_tolerance_pct")
        last_scored      = derived.get("last_scored", "just now")
    else:
        risk_score       = derived.get("risk_score")
        risk_label       = derived.get("risk_label")
        completeness_pct = None
        answered_count   = None
        max_dd           = derived.get("max_drawdown_tolerance_pct")
        last_scored      = derived.get("last_scored")

    col_score, col_label, col_complete, col_dd = st.columns(4)

    with col_score:
        st.metric("Risk Score", (_fmt_score(risk_score) + " / 100") if risk_score is not None else "—")

    with col_label:
        label_display = _LABEL_DISPLAY.get(risk_label, risk_label or "—")
        colour = _LABEL_COLOUR.get(risk_label, "#555")
        st.markdown(
            f"**Risk Profile**<br>"
            f"<span style='color:{colour}; font-size:1.2em; font-weight:bold'>{label_display}</span>",
            unsafe_allow_html=True,
        )

    with col_complete:
        if completeness_pct is not None:
            st.metric(
                "Questionnaire",
                f"{_fmt_pct(completeness_pct)}",
                help=f"{answered_count} of {len(questions)} questions answered",
            )
            st.progress(int(completeness_pct))
        else:
            st.metric("Questionnaire", "Answer questions →")

    with col_dd:
        st.metric(
            "Max Drawdown Tolerance",
            _fmt_pct(max_dd),
            help="Maximum single-year decline you can tolerate without changing your plan.",
        )

    if last_scored:
        st.caption(f"Last scored: {last_scored}")

    st.divider()
    if not _has_answers:
        st.warning("Answer the **Questionnaire** tab first, then return here to run the scorer.")

    btn_col, clr_col = st.columns([1, 7])
    with btn_col:
        if st.button("Run Scorer", type="primary", disabled=not _has_answers):
            with st.spinner("Scoring…"):
                st.session_state["profile_score_result"] = _run_profile_score()
            st.rerun()
    with clr_col:
        if st.session_state.get("profile_score_result") and st.button("Clear"):
            st.session_state.pop("profile_score_result", None)
            st.rerun()

    if score_result and "error" in score_result:
        st.error(score_result["error"])

    # Per-question breakdown
    if score_result and "scored_questions" in score_result:
        answered_qs   = [q for q in score_result["scored_questions"] if q["answered"]]
        unanswered_qs = [q for q in score_result["scored_questions"] if not q["answered"]]

        if answered_qs:
            st.divider()
            st.subheader("Question Breakdown")
            q_lookup = {q["question_id"]: q for q in questions}
            rows = []
            for sq in answered_qs:
                qdef = q_lookup.get(sq["question_id"], {})
                text = qdef.get("question_text", "").strip()
                rows.append({
                    "ID":       sq["question_id"],
                    "Question": (text[:80] + "…") if len(text) > 80 else text,
                    "Weight":   sq["weight"],
                    "Score":    sq["score"],
                })
            import pandas as pd
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if unanswered_qs:
            with st.expander(f"{len(unanswered_qs)} unanswered question(s) — go to Questionnaire tab"):
                q_lookup = {q["question_id"]: q for q in questions}
                for sq in unanswered_qs:
                    qdef = q_lookup.get(sq["question_id"], {})
                    st.write(f"**{sq['question_id']}** — {qdef.get('question_text', '').strip()}")

    # Philosophy summary
    if profile.get("philosophy"):
        st.divider()
        st.subheader("Investment Philosophy")
        st.markdown(profile["philosophy"])

    # Objectives summary
    if profile:
        st.divider()
        st.subheader("Objectives & Constraints")
        goals       = profile.get("goals", {})
        constraints = profile.get("constraints", {})
        tax         = profile.get("tax", {})

        g_col, c_col, t_col = st.columns(3)
        with g_col:
            st.markdown("**Goals**")
            st.write(f"Primary: `{goals.get('primary', '—')}`")
            if goals.get("secondary"):
                st.write(f"Secondary: `{goals.get('secondary')}`")
        with c_col:
            st.markdown("**Constraints**")
            st.write(f"Max single position: `{constraints.get('max_single_position_pct', '—')}%`")
            st.write(f"Max sector: `{constraints.get('max_sector_pct', '—')}%`")
            excluded = constraints.get("excluded_sectors", [])
            st.write(f"Excluded sectors: {', '.join(excluded) if excluded else 'None'}")
            st.write(f"Min cash buffer: `{constraints.get('min_cash_buffer_years', '—')} yrs`")
        with t_col:
            st.markdown("**Tax**")
            reg_emphasis = "Yes" if tax.get("registered_emphasis") else "No"
            st.write(f"Registered emphasis: `{reg_emphasis}`")
            if tax.get("notes"):
                st.caption(tax["notes"])


# ===========================================================================
# Tab 2 — Questionnaire
# ===========================================================================
with tab_q:
    st.markdown(
        "Answer each question below and click **Save & Score**. "
        "Your answers are saved locally and never committed to git."
    )

    if not questions:
        st.warning("questions.yaml not found — cannot render questionnaire.")
    else:
        current_answers = _load_answers()

        with st.form("questionnaire_form"):
            form_values: dict[str, object] = {}

            for q in questions:
                qid   = q["question_id"]
                qtext = q["question_text"].strip()
                atype = q["answer_type"]
                cur   = current_answers.get(qid, {})
                cur_val = cur.get("value") if cur.get("answered") else None

                st.markdown(f"**{qid} — {qtext}**")

                if atype == "choice":
                    options = q.get("options", [])
                    raw_opts = [None] + options
                    labels   = ["— not answered —"] + [
                        _OPTION_LABELS.get(o, o) for o in options
                    ]
                    idx = (options.index(cur_val) + 1) if cur_val in options else 0
                    selected = st.radio(
                        qtext,
                        options=labels,
                        index=idx,
                        key=f"q_{qid}",
                        label_visibility="collapsed",
                    )
                    form_values[qid] = raw_opts[labels.index(selected)]

                elif atype in ("int", "float"):
                    dtype   = int if atype == "int" else float
                    min_v   = dtype(q.get("min", 0))
                    max_v   = dtype(q.get("max", 100))
                    step    = 1 if atype == "int" else 0.5
                    unit    = q.get("unit", "")
                    cur_num = dtype(cur_val) if cur_val is not None else None
                    val = st.number_input(
                        f"{min_v}–{max_v} {unit}  (leave blank to skip)",
                        min_value=min_v,
                        max_value=max_v,
                        value=cur_num,
                        step=step,
                        key=f"q_{qid}",
                        label_visibility="visible",
                    )
                    form_values[qid] = val

                st.write("")  # spacing

            submitted = st.form_submit_button("Save Answers & Run Scorer", type="primary")

        if submitted:
            _save_answers(questions, form_values)
            with st.spinner("Scoring…"):
                st.session_state["profile_score_result"] = _run_profile_score()
            answered_n = sum(1 for v in form_values.values() if v is not None)
            st.success(f"Saved {answered_n} of {len(questions)} answers. Score updated.")
            st.rerun()

    if _profile_complete:
        st.success("Profile complete. Head to the **Score** tab to review your risk profile, then return to the Hub.")
        st.page_link("Home.py", label="← Back to Hub")


# ===========================================================================
# Tab 3 — Investment Approach
# ===========================================================================
with tab_approach:
    st.markdown(
        "Describe your overall investment approach, constraints, and tax considerations. "
        "These feed into the commentary engine."
    )

    goals       = profile.get("goals", {})
    th          = profile.get("time_horizon", {})
    constraints = profile.get("constraints", {})
    tax         = profile.get("tax", {})
    retirement  = profile.get("retirement", {})

    with st.form("profile_form"):
        st.subheader("Investment Philosophy")
        philosophy = st.text_area(
            "Describe your overall investment approach in your own words",
            value=profile.get("philosophy", ""),
            height=220,
            placeholder=(
                "e.g. A multi-bucket strategy balancing income generation, long-term growth, "
                "tax efficiency, and legacy planning. Conservative yet opportunistic, with a "
                "Canadian tilt and emphasis on energy, banks, utilities, and telecoms..."
            ),
            help="This narrative is passed directly to the commentary engine to personalise its analysis.",
        )

        st.subheader("Goals")
        goal_options = [
            "capital_preservation", "income", "balanced", "growth", "aggressive_growth"
        ]
        goal_labels = [_OPTION_LABELS.get(o, o) for o in goal_options]

        cur_primary = goals.get("primary", "balanced")
        pri_idx = goal_options.index(cur_primary) if cur_primary in goal_options else 2
        primary_sel = st.selectbox(
            "Primary goal",
            options=goal_labels,
            index=pri_idx,
        )
        secondary = st.text_input(
            "Secondary goal (optional free text)",
            value=goals.get("secondary", ""),
            placeholder="e.g. income, capital preservation",
        )

        st.subheader("Time Horizon")
        th_desc = st.text_area(
            "Description",
            value=th.get("description", ""),
            height=80,
            placeholder="e.g. Retired. Primary draw-down window is 20+ years.",
        )
        th_years = st.number_input(
            "Years to significant drawdown",
            min_value=0, max_value=50,
            value=int(th.get("years_to_significant_drawdown") or 0),
            step=1,
        )

        st.subheader("Constraints")
        c1, c2 = st.columns(2)
        with c1:
            max_pos = st.number_input(
                "Max single position (%)",
                min_value=0.0, max_value=100.0,
                value=float(constraints.get("max_single_position_pct") or 20.0),
                step=1.0,
            )
            min_cash = st.number_input(
                "Min cash buffer (years of expenses)",
                min_value=0.0, max_value=20.0,
                value=float(constraints.get("min_cash_buffer_years") or 2.0),
                step=0.5,
            )
        with c2:
            max_sector = st.number_input(
                "Max sector concentration (%)",
                min_value=0.0, max_value=100.0,
                value=float(constraints.get("max_sector_pct") or 40.0),
                step=1.0,
            )
            excluded_raw = st.text_input(
                "Excluded sectors (comma-separated)",
                value=", ".join(constraints.get("excluded_sectors") or []),
                placeholder="e.g. Cannabis, Crypto",
            )

        st.subheader("Tax")
        t1, t2 = st.columns([1, 3])
        with t1:
            reg_emphasis = st.checkbox(
                "Registered account emphasis (TFSA/RRSP priority)",
                value=bool(tax.get("registered_emphasis", True)),
            )
        with t2:
            tax_notes = st.text_area(
                "Tax notes",
                value=tax.get("notes", ""),
                height=80,
                placeholder="e.g. TFSA and RRSP/RRIF optimization. OAS clawback considerations.",
            )

        st.subheader("Retirement")
        r1, r2 = st.columns(2)
        with r1:
            annual_exp = st.number_input(
                "Annual expenses estimate ($)",
                min_value=0,
                value=int(retirement.get("annual_expenses_estimate") or 0),
                step=1000,
            )
        with r2:
            guaranteed_pct = st.number_input(
                "Guaranteed income coverage (% of expenses)",
                min_value=0, max_value=100,
                value=int(retirement.get("guaranteed_income_pct") or 0),
                step=5,
            )
        ret_notes = st.text_area(
            "Retirement notes",
            value=retirement.get("notes", ""),
            height=60,
            placeholder="e.g. CPP and OAS cover roughly 40% of expenses.",
        )

        save_profile = st.form_submit_button("Save Investment Approach", type="primary")

    if save_profile:
        primary_key = goal_options[goal_labels.index(primary_sel)]
        excluded_list = [s.strip() for s in excluded_raw.split(",") if s.strip()]
        updated = {
            "philosophy": philosophy or None,
            "goals": {
                "primary":   primary_key,
                "secondary": secondary or None,
            },
            "time_horizon": {
                "description":                  th_desc,
                "years_to_significant_drawdown": th_years,
            },
            "constraints": {
                "max_single_position_pct": max_pos,
                "max_sector_pct":          max_sector,
                "excluded_sectors":        excluded_list,
                "min_cash_buffer_years":   min_cash,
            },
            "tax": {
                "registered_emphasis": reg_emphasis,
                "notes":               tax_notes,
            },
            "retirement": {
                "annual_expenses_estimate": annual_exp or None,
                "guaranteed_income_pct":    guaranteed_pct or None,
                "notes":                    ret_notes,
            },
        }
        _save_profile(updated)
        st.success("Investment approach saved to profile.yaml.")
        st.rerun()
