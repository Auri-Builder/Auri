"""
ORI Personal — Investor Profile page (pages/profile.py)

Displays Jeff's risk score, profile completeness, key constraints,
and allows re-scoring by triggering portfolio_profile_v0.

Dev mode (dashboard.yaml → dev_direct_call: true):
    Calls handle_portfolio_profile_v0 directly.

Governed mode:
    Submits portfolio_profile_v0 job via the job queue.

No raw answer values are displayed — only derived aggregates.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_DIR = PROJECT_ROOT / "data" / "portfolio"
DASHBOARD_CONFIG_PATH = PROJECT_ROOT / "dashboard.yaml"

PROFILE_PATH    = PORTFOLIO_DIR / "profile.yaml"
QUESTIONS_PATH  = PORTFOLIO_DIR / "questions.yaml"
ANSWERS_PATH    = PORTFOLIO_DIR / "answers.yaml"

# ---------------------------------------------------------------------------
# Risk label → display colour
# ---------------------------------------------------------------------------

_LABEL_COLOUR = {
    "conservative":           "#1565c0",   # blue
    "moderately_conservative": "#0277bd",  # light blue
    "balanced":               "#2e7d32",   # green
    "growth":                 "#f57f17",   # amber
    "aggressive":             "#b71c1c",   # red
}

_LABEL_DISPLAY = {
    "conservative":            "Conservative",
    "moderately_conservative": "Moderately Conservative",
    "balanced":                "Balanced",
    "growth":                  "Growth",
    "aggressive":              "Aggressive",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_dashboard_config() -> dict:
    if not DASHBOARD_CONFIG_PATH.exists():
        return {}
    with DASHBOARD_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _load_profile() -> dict:
    """Load profile.yaml if it exists; return {} otherwise."""
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


def _run_profile_score() -> dict:
    """Call portfolio_profile_v0 via dev or governed path."""
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

st.set_page_config(page_title="ORI · Investor Profile", layout="wide")
st.title("Investor Profile")

# ── Missing file warnings ─────────────────────────────────────────────────────
missing = []
if not PROFILE_PATH.exists():
    missing.append("`data/portfolio/profile.yaml`")
if not ANSWERS_PATH.exists():
    missing.append("`data/portfolio/answers.yaml`")
if missing:
    st.warning(
        f"Profile files not found: {', '.join(missing)}. "
        "Copy the templates from the repo and fill in your details, "
        "then re-open this page."
    )

# ── Load profile (may be empty / outdated) ────────────────────────────────────
profile = _load_profile()
derived = profile.get("derived", {})

# ── Row 1: Current score + completeness ──────────────────────────────────────
st.subheader("Risk Score")

questions = _load_questions()
total_q = len(questions)

# Try to read completeness from last scored run stored in session state,
# or fall back to the profile's derived fields.
score_result = st.session_state.get("profile_score_result")
if score_result and "error" not in score_result:
    risk_score        = score_result.get("risk_score")
    risk_label        = score_result.get("risk_label")
    completeness_pct  = score_result.get("completeness_pct", 0.0)
    answered_count    = score_result.get("answered_count", 0)
    max_dd            = score_result.get("max_drawdown_tolerance_pct")
    last_scored       = derived.get("last_scored", "just now")
else:
    risk_score        = derived.get("risk_score")
    risk_label        = derived.get("risk_label")
    completeness_pct  = None   # unknown until scorer runs
    answered_count    = None
    max_dd            = derived.get("max_drawdown_tolerance_pct")
    last_scored       = derived.get("last_scored")

col_score, col_label, col_complete, col_dd = st.columns(4)

with col_score:
    st.metric("Risk Score", _fmt_score(risk_score) + " / 100" if risk_score is not None else "—")

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
            help=f"{answered_count} of {total_q} questions answered",
        )
        st.progress(int(completeness_pct))
    else:
        st.metric("Questionnaire", "Run scorer →")

with col_dd:
    st.metric(
        "Max Drawdown Tolerance",
        _fmt_pct(max_dd),
        help="Maximum single-year portfolio decline you indicated you could tolerate (q05).",
    )

if last_scored:
    st.caption(f"Last scored: {last_scored}")

# ── Row 2: Score / Re-score button ───────────────────────────────────────────
st.divider()
btn_col, clr_col = st.columns([1, 7])
with btn_col:
    if st.button("Run Scorer", type="primary"):
        with st.spinner("Scoring…"):
            st.session_state["profile_score_result"] = _run_profile_score()
        st.rerun()
with clr_col:
    if st.session_state.get("profile_score_result") and st.button("Clear"):
        st.session_state.pop("profile_score_result", None)
        st.rerun()

if score_result and "error" in score_result:
    st.error(score_result["error"])

# ── Row 3: Per-question breakdown (answered questions only) ───────────────────
if score_result and "scored_questions" in score_result:
    answered_qs = [q for q in score_result["scored_questions"] if q["answered"]]
    unanswered_qs = [q for q in score_result["scored_questions"] if not q["answered"]]

    if answered_qs:
        st.divider()
        st.subheader("Question Breakdown")
        q_lookup = {q["question_id"]: q for q in questions}
        rows = []
        for sq in answered_qs:
            qdef = q_lookup.get(sq["question_id"], {})
            rows.append({
                "ID":     sq["question_id"],
                "Question": qdef.get("question_text", "").strip()[:80] + "…"
                            if len(qdef.get("question_text", "")) > 80
                            else qdef.get("question_text", "").strip(),
                "Weight": sq["weight"],
                "Score":  sq["score"],
            })
        import pandas as pd
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

    if unanswered_qs:
        with st.expander(f"{len(unanswered_qs)} unanswered question(s)"):
            q_lookup = {q["question_id"]: q for q in questions}
            for sq in unanswered_qs:
                qdef = q_lookup.get(sq["question_id"], {})
                st.write(
                    f"**{sq['question_id']}** — {qdef.get('question_text', '').strip()}"
                )

# ── Row 4: Profile objectives + constraints ───────────────────────────────────
if profile:
    st.divider()
    st.subheader("Objectives & Constraints")

    goals = profile.get("goals", {})
    constraints = profile.get("constraints", {})
    tax = profile.get("tax", {})

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

# ── Row 5: How to update your answers ────────────────────────────────────────
with st.expander("How to update your answers"):
    st.markdown(
        """
Edit `data/portfolio/answers.yaml` directly in any text editor.

For each question:
- Set `answered: true`
- Set `value:` to your answer (see `questions.yaml` for valid options)

Then click **Run Scorer** to refresh your risk score.

Your answers are **gitignored** and never committed to the repository.
"""
    )
