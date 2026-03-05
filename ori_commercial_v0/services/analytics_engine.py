"""
ori_commercial_v0/services/analytics_engine.py
───────────────────────────────────────────────
STUB — not yet implemented.

Pure-function analytics over a PortfolioSnapshot.

Design notes:
- All functions are pure: (Snapshot, ...) → result dict.
- No I/O, no database calls, no LLM calls.
- Snapshots are the only input — never live holdings.
- Functions must be deterministic: same snapshot → same result.

IMPORTANT: Do NOT import from agents/, core/, or pages/.
"""

from __future__ import annotations


def compute_performance(snapshot, benchmark_snapshot=None) -> dict:
    """
    Compute portfolio performance metrics against an optional benchmark.

    Parameters
    ----------
    snapshot : PortfolioSnapshot
    benchmark_snapshot : PortfolioSnapshot, optional

    Returns
    -------
    dict with keys: total_return_pct, benchmark_return_pct, alpha, etc.
    """
    raise NotImplementedError("analytics_engine is a stub.")


def compute_sector_drift(snapshot_a, snapshot_b) -> dict:
    """
    Compute sector weight changes between two snapshots.

    Returns a dict of sector → {weight_a, weight_b, drift_pct}.
    """
    raise NotImplementedError("analytics_engine is a stub.")


def compute_income_yield(snapshot) -> dict:
    """
    Estimate annual income yield from dividends/distributions.
    Requires yield data per symbol (future: market data connector).
    """
    raise NotImplementedError("analytics_engine is a stub.")
