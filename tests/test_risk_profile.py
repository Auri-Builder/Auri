"""
Tests for agents/ori_ia/risk_profile.py

All tests use in-memory question/answer dicts — no file I/O.
"""

import pytest

from agents.ori_ia.risk_profile import compute_risk_score, _score_question, _risk_label


# ---------------------------------------------------------------------------
# Fixtures — minimal question definitions
# ---------------------------------------------------------------------------

MAP_QUESTION = {
    "question_id": "q01",
    "weight": 20,
    "answer_type": "choice",
    "scoring_rule": {
        "type": "map",
        "scores": {
            "capital_preservation": 10,
            "income": 25,
            "balanced": 50,
            "growth": 75,
            "aggressive_growth": 95,
        },
    },
}

LINEAR_QUESTION = {
    "question_id": "q04",
    "weight": 15,
    "answer_type": "int",
    "scoring_rule": {"type": "linear", "min": 0, "max": 100},
}

INVERSE_QUESTION = {
    "question_id": "qX",
    "weight": 10,
    "answer_type": "int",
    "scoring_rule": {"type": "inverse", "min": 0, "max": 100},
}

DRAWDOWN_QUESTION = {
    "question_id": "q05",
    "weight": 15,
    "answer_type": "int",
    "scoring_rule": {"type": "linear", "min": 0, "max": 60},
}

ALL_QUESTIONS = [
    MAP_QUESTION,
    LINEAR_QUESTION,
    INVERSE_QUESTION,
    DRAWDOWN_QUESTION,
]


# ---------------------------------------------------------------------------
# _score_question — map rule
# ---------------------------------------------------------------------------

class TestScoreQuestionMap:

    def test_known_answer_returns_mapped_score(self):
        assert _score_question(MAP_QUESTION, "balanced") == 50.0

    def test_all_map_options(self):
        expected = {
            "capital_preservation": 10.0,
            "income": 25.0,
            "balanced": 50.0,
            "growth": 75.0,
            "aggressive_growth": 95.0,
        }
        for value, score in expected.items():
            assert _score_question(MAP_QUESTION, value) == score

    def test_unknown_answer_raises(self):
        with pytest.raises(ValueError, match="not in scoring map"):
            _score_question(MAP_QUESTION, "invalid_option")

    def test_case_sensitive(self):
        with pytest.raises(ValueError):
            _score_question(MAP_QUESTION, "Balanced")


# ---------------------------------------------------------------------------
# _score_question — linear rule
# ---------------------------------------------------------------------------

class TestScoreQuestionLinear:

    def test_min_value_returns_zero(self):
        assert _score_question(LINEAR_QUESTION, 0) == 0.0

    def test_max_value_returns_hundred(self):
        assert _score_question(LINEAR_QUESTION, 100) == 100.0

    def test_midpoint_returns_fifty(self):
        assert _score_question(LINEAR_QUESTION, 50) == 50.0

    def test_float_input_accepted(self):
        score = _score_question(LINEAR_QUESTION, 25.0)
        assert score == pytest.approx(25.0)

    def test_clamped_below_min(self):
        assert _score_question(LINEAR_QUESTION, -10) == 0.0

    def test_clamped_above_max(self):
        assert _score_question(LINEAR_QUESTION, 200) == 100.0

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError, match="expected numeric"):
            _score_question(LINEAR_QUESTION, "fifty")

    def test_equal_min_max_raises(self):
        bad_q = {
            "question_id": "qBad",
            "scoring_rule": {"type": "linear", "min": 5, "max": 5},
        }
        with pytest.raises(ValueError, match="distinct min and max"):
            _score_question(bad_q, 5)


# ---------------------------------------------------------------------------
# _score_question — inverse rule
# ---------------------------------------------------------------------------

class TestScoreQuestionInverse:

    def test_min_value_returns_hundred(self):
        assert _score_question(INVERSE_QUESTION, 0) == 100.0

    def test_max_value_returns_zero(self):
        assert _score_question(INVERSE_QUESTION, 100) == 0.0

    def test_midpoint_returns_fifty(self):
        assert _score_question(INVERSE_QUESTION, 50) == 50.0


# ---------------------------------------------------------------------------
# _score_question — unknown rule
# ---------------------------------------------------------------------------

class TestScoreQuestionUnknown:

    def test_unknown_rule_type_raises(self):
        bad_q = {
            "question_id": "qBad",
            "scoring_rule": {"type": "fuzzy"},
        }
        with pytest.raises(ValueError, match="unknown scoring rule type"):
            _score_question(bad_q, "anything")


# ---------------------------------------------------------------------------
# _risk_label
# ---------------------------------------------------------------------------

class TestRiskLabel:

    def test_zero_is_conservative(self):
        assert _risk_label(0) == "conservative"

    def test_ten_is_conservative(self):
        assert _risk_label(10) == "conservative"

    def test_twenty_is_moderately_conservative(self):
        assert _risk_label(20) == "moderately_conservative"

    def test_forty_is_balanced(self):
        assert _risk_label(40) == "balanced"

    def test_fifty_is_balanced(self):
        assert _risk_label(50) == "balanced"

    def test_sixty_is_growth(self):
        assert _risk_label(60) == "growth"

    def test_eighty_is_aggressive(self):
        assert _risk_label(80) == "aggressive"

    def test_hundred_is_aggressive(self):
        assert _risk_label(100) == "aggressive"


# ---------------------------------------------------------------------------
# compute_risk_score — core logic
# ---------------------------------------------------------------------------

class TestComputeRiskScore:

    def test_no_answers_returns_zero_score(self):
        result = compute_risk_score(ALL_QUESTIONS, {})
        assert result["risk_score"] == 0.0

    def test_no_answers_completeness_is_zero(self):
        result = compute_risk_score(ALL_QUESTIONS, {})
        assert result["completeness_pct"] == 0.0

    def test_all_answered_completeness_is_100(self):
        answers = {
            "q01": "balanced",
            "q04": 50,
            "qX": 50,
            "q05": 30,
        }
        result = compute_risk_score(ALL_QUESTIONS, answers)
        assert result["completeness_pct"] == 100.0

    def test_partial_answers_completeness(self):
        answers = {"q01": "balanced"}
        result = compute_risk_score(ALL_QUESTIONS, answers)
        assert result["completeness_pct"] == 25.0

    def test_answered_count_correct(self):
        answers = {"q01": "growth", "q04": 80}
        result = compute_risk_score(ALL_QUESTIONS, answers)
        assert result["answered_count"] == 2

    def test_total_count_correct(self):
        result = compute_risk_score(ALL_QUESTIONS, {})
        assert result["total_count"] == 4

    def test_single_map_answer_score(self):
        # Only q01 answered with "balanced" (score=50, weight=20)
        # answered_weight_sum=20, risk_score = 50*20 / 20 = 50
        result = compute_risk_score(ALL_QUESTIONS, {"q01": "balanced"})
        assert result["risk_score"] == 50.0

    def test_single_linear_answer_score(self):
        # Only q04 answered with 75 (score=75, weight=15)
        result = compute_risk_score(ALL_QUESTIONS, {"q04": 75})
        assert result["risk_score"] == pytest.approx(75.0)

    def test_weighted_average_two_questions(self):
        # q01: balanced=50, weight=20
        # q04: 100=100, weight=15
        # weighted = (50*20 + 100*15) / (20+15) = (1000+1500)/35 = 71.43
        answers = {"q01": "balanced", "q04": 100}
        result = compute_risk_score(ALL_QUESTIONS, answers)
        assert result["risk_score"] == pytest.approx(71.43, abs=0.01)

    def test_risk_label_populated(self):
        result = compute_risk_score(ALL_QUESTIONS, {"q01": "growth"})
        assert result["risk_label"] == "growth"

    def test_scored_questions_length(self):
        result = compute_risk_score(ALL_QUESTIONS, {})
        assert len(result["scored_questions"]) == 4

    def test_unanswered_question_in_scored_list(self):
        result = compute_risk_score(ALL_QUESTIONS, {})
        for sq in result["scored_questions"]:
            assert sq["answered"] is False
            assert sq["score"] is None

    def test_answered_question_in_scored_list(self):
        result = compute_risk_score(ALL_QUESTIONS, {"q01": "income"})
        q01 = next(sq for sq in result["scored_questions"] if sq["question_id"] == "q01")
        assert q01["answered"] is True
        assert q01["score"] == 25.0

    def test_raw_answer_value_not_in_output(self):
        result = compute_risk_score(ALL_QUESTIONS, {"q01": "aggressive_growth"})
        result_str = str(result)
        assert "aggressive_growth" not in result_str

    def test_drawdown_tolerance_extracted_from_q05(self):
        answers = {"q05": 25}
        result = compute_risk_score(ALL_QUESTIONS, answers)
        assert result["max_drawdown_tolerance_pct"] == 25.0

    def test_drawdown_tolerance_none_when_q05_absent(self):
        result = compute_risk_score(ALL_QUESTIONS, {"q01": "balanced"})
        assert result["max_drawdown_tolerance_pct"] is None

    def test_empty_questions_list(self):
        result = compute_risk_score([], {})
        assert result["risk_score"] == 0.0
        assert result["completeness_pct"] == 0.0
        assert result["total_count"] == 0


# ---------------------------------------------------------------------------
# Governance: scored_questions must not expose raw values
# ---------------------------------------------------------------------------

class TestGovernance:

    def test_no_raw_choice_answer_in_output(self):
        answers = {"q01": "capital_preservation"}
        result = compute_risk_score(ALL_QUESTIONS, answers)
        for sq in result["scored_questions"]:
            assert "capital_preservation" not in str(sq)

    def test_no_raw_numeric_answer_in_scored_questions(self):
        # q04 answered with 42 — only the derived score should appear, not 42
        answers = {"q04": 42}
        result = compute_risk_score(ALL_QUESTIONS, answers)
        q04 = next(sq for sq in result["scored_questions"] if sq["question_id"] == "q04")
        assert q04["score"] == pytest.approx(42.0)  # score happens to equal value here
        # But the raw value 42 should not appear as a separate key
        assert "value" not in q04
        assert "answer" not in q04


# ---------------------------------------------------------------------------
# YAML parsing — load_questions with a real temp file
# ---------------------------------------------------------------------------

class TestLoadQuestions:

    def test_load_questions_parses_list(self, tmp_path):
        from agents.ori_ia.risk_profile import load_questions
        yaml_content = """
version: "1.0"
questions:
  - question_id: qT
    weight: 10
    answer_type: choice
    scoring_rule:
      type: map
      scores:
        yes: 80
        no: 20
"""
        p = tmp_path / "questions.yaml"
        p.write_text(yaml_content)
        questions = load_questions(p)
        assert len(questions) == 1
        assert questions[0]["question_id"] == "qT"

    def test_load_questions_empty_file_returns_empty(self, tmp_path):
        from agents.ori_ia.risk_profile import load_questions
        p = tmp_path / "questions.yaml"
        p.write_text("version: '1.0'\n")
        assert load_questions(p) == []


class TestLoadAnswers:

    def test_load_answers_only_returns_answered(self, tmp_path):
        from agents.ori_ia.risk_profile import load_answers
        yaml_content = """
version: "1.0"
answers:
  - question_id: q01
    answered: true
    value: balanced
  - question_id: q02
    answered: false
    value: null
  - question_id: q03
    answered: true
    value: 42
"""
        p = tmp_path / "answers.yaml"
        p.write_text(yaml_content)
        answers = load_answers(p)
        assert set(answers.keys()) == {"q01", "q03"}
        assert answers["q01"] == "balanced"
        assert answers["q03"] == 42

    def test_load_answers_null_value_excluded(self, tmp_path):
        from agents.ori_ia.risk_profile import load_answers
        yaml_content = """
version: "1.0"
answers:
  - question_id: q01
    answered: true
    value: null
"""
        p = tmp_path / "answers.yaml"
        p.write_text(yaml_content)
        assert load_answers(p) == {}
