"""
ori_commercial_v0/services/risk_engine.py
──────────────────────────────────────────
STUB — not yet implemented.

IPS compliance checking and risk scoring over a PortfolioSnapshot.

Design notes:
- Pure functions: (Snapshot, IPS) → compliance result.
- No I/O, no database calls, no LLM calls.
- Must be deterministic and auditable.
- All violations reference the IPS constraint that was breached.

IMPORTANT: Do NOT import from agents/, core/, or pages/.
"""

from __future__ import annotations


def check_ips_compliance(snapshot, ips) -> dict:
    """
    Check a PortfolioSnapshot against an IPS for policy violations.

    Parameters
    ----------
    snapshot : PortfolioSnapshot
    ips : IPS

    Returns
    -------
    dict with keys:
        compliant (bool),
        violations (list[dict]):
            each violation has: constraint, actual_value, limit_value, severity
    """
    raise NotImplementedError("risk_engine is a stub.")


def compute_client_risk_score(questions: list[dict], answers: dict) -> dict:
    """
    Deterministic risk score from a questionnaire.

    Same algorithm as ORI Personal's risk_profile.py but typed against
    the commercial domain model.  Implementation will be extracted here
    when the commercial track is wired.

    Returns: risk_score (float 0-100), risk_tolerance (RiskTolerance),
             completeness_pct, max_drawdown_tolerance_pct.
    """
    raise NotImplementedError("risk_engine is a stub.")


def flag_concentration(snapshot, max_position_pct: float, max_sector_pct: float) -> list[dict]:
    """
    Return a list of concentration flags for positions or sectors that
    exceed the given thresholds.
    """
    raise NotImplementedError("risk_engine is a stub.")
