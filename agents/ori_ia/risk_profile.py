"""
agents/ori_ia/risk_profile.py
─────────────────────────────
Deterministic risk-score computation for ORI Personal.

Inputs
------
  questions.yaml  — question manifest with weights and scoring rules
                    (tracked in git, no personal data)
  answers.yaml    — Jeff's answers (gitignored, personal data)

Output
------
  dict with:
    risk_score          float  0–100
    risk_label          str    one of RISK_LABELS
    completeness_pct    float  0–100  (answered / total questions)
    answered_count      int
    total_count         int
    max_drawdown_tolerance_pct  float | None  (from q05 if answered)
    scored_questions    list[dict]  — per-question breakdown (no raw answers)

Governance
----------
- Pure functions only; no I/O except load_* helpers.
- No raw answer values appear in the output dict — only derived scores.
- Raises ValueError on invalid scoring rules or missing required fields,
  so callers get a clear error rather than a silent wrong result.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_QUESTIONS_PATH = (
    Path(__file__).parent.parent.parent / "data" / "portfolio" / "questions.yaml"
).resolve()

_ANSWERS_PATH = (
    Path(__file__).parent.parent.parent / "data" / "portfolio" / "answers.yaml"
).resolve()

# Thresholds that map a numeric risk_score to a human label.
# Boundaries are inclusive on the lower end.
_RISK_THRESHOLDS = [
    (0,  20,  "conservative"),
    (20, 40,  "moderately_conservative"),
    (40, 60,  "balanced"),
    (60, 80,  "growth"),
    (80, 101, "aggressive"),
]


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_questions(path: Path | None = None) -> list[dict]:
    """Parse questions.yaml and return the list of question dicts."""
    p = path or _QUESTIONS_PATH
    with open(p, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("questions", [])


def load_answers(path: Path | None = None) -> dict[str, Any]:
    """
    Parse answers.yaml and return a dict keyed by question_id.

    Only answered questions (answered: true, value not None) are included.
    """
    p = path or _ANSWERS_PATH
    with open(p, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    result: dict[str, Any] = {}
    for entry in data.get("answers", []):
        if entry.get("answered") and entry.get("value") is not None:
            result[entry["question_id"]] = entry["value"]
    return result


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_question(question: dict, value: Any) -> float:
    """
    Apply the question's scoring_rule to a raw answer value.

    Returns a float in [0, 100].
    Raises ValueError for unrecognised rule types or invalid values.
    """
    rule = question.get("scoring_rule", {})
    rule_type = rule.get("type")

    if rule_type == "map":
        scores = rule.get("scores", {})
        if value not in scores:
            raise ValueError(
                f"Question {question['question_id']!r}: value {value!r} not in "
                f"scoring map. Valid options: {list(scores)}"
            )
        return float(scores[value])

    if rule_type in ("linear", "inverse"):
        lo = rule.get("min")
        hi = rule.get("max")
        if lo is None or hi is None or hi == lo:
            raise ValueError(
                f"Question {question['question_id']!r}: linear/inverse rule "
                f"requires distinct min and max."
            )
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"Question {question['question_id']!r}: expected numeric value, "
                f"got {value!r}."
            )
        clamped = max(lo, min(hi, numeric))
        score = (clamped - lo) / (hi - lo) * 100.0
        return (100.0 - score) if rule_type == "inverse" else score

    raise ValueError(
        f"Question {question['question_id']!r}: unknown scoring rule type "
        f"{rule_type!r}. Expected 'map', 'linear', or 'inverse'."
    )


def _risk_label(score: float) -> str:
    for lo, hi, label in _RISK_THRESHOLDS:
        if lo <= score < hi:
            return label
    return "aggressive"  # score == 100 edge case


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def compute_risk_score(
    questions: list[dict],
    answers: dict[str, Any],
) -> dict:
    """
    Compute a weighted risk score from question definitions and answers.

    Parameters
    ----------
    questions : list[dict]
        Parsed from questions.yaml.
    answers : dict[str, Any]
        Keyed by question_id, containing only answered questions.

    Returns
    -------
    dict
        risk_score, risk_label, completeness_pct, answered_count,
        total_count, max_drawdown_tolerance_pct, scored_questions.
    """
    total_count = len(questions)
    answered_count = 0

    # Weighted sum over answered questions only.
    # We normalise by the *answered* weight sum so a partially-complete
    # questionnaire still produces a meaningful score rather than pulling
    # everything toward 0.
    weighted_score_sum = 0.0
    answered_weight_sum = 0.0
    max_drawdown_tolerance_pct: float | None = None

    scored_questions: list[dict] = []

    for q in questions:
        qid = q["question_id"]
        weight = float(q.get("weight", 0))
        answered = qid in answers

        if answered:
            raw_value = answers[qid]
            q_score = _score_question(q, raw_value)
            weighted_score_sum += q_score * weight
            answered_weight_sum += weight
            answered_count += 1

            # Extract max drawdown tolerance from q05 (linear int answer)
            if qid == "q05" and q.get("answer_type") in ("int", "float"):
                try:
                    max_drawdown_tolerance_pct = float(raw_value)
                except (TypeError, ValueError):
                    pass

            scored_questions.append({
                "question_id": qid,
                "weight": weight,
                "score": round(q_score, 2),
                "answered": True,
            })
        else:
            scored_questions.append({
                "question_id": qid,
                "weight": weight,
                "score": None,
                "answered": False,
            })

    # Normalised risk score (over answered weights only)
    if answered_weight_sum > 0:
        risk_score = round(weighted_score_sum / answered_weight_sum, 2)
    else:
        risk_score = 0.0

    completeness_pct = round(answered_count / total_count * 100, 1) if total_count else 0.0

    return {
        "risk_score": risk_score,
        "risk_label": _risk_label(risk_score),
        "completeness_pct": completeness_pct,
        "answered_count": answered_count,
        "total_count": total_count,
        "max_drawdown_tolerance_pct": max_drawdown_tolerance_pct,
        "scored_questions": scored_questions,
    }


def load_and_score(
    questions_path: Path | None = None,
    answers_path: Path | None = None,
) -> dict:
    """
    Convenience wrapper: load both YAMLs and return compute_risk_score result.

    Raises FileNotFoundError if either file is missing.
    """
    questions = load_questions(questions_path)
    answers = load_answers(answers_path)
    return compute_risk_score(questions, answers)
