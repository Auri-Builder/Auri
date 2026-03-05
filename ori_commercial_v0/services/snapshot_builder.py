"""
ori_commercial_v0/services/snapshot_builder.py
───────────────────────────────────────────────
STUB — not yet implemented.

Builds an immutable PortfolioSnapshot from live domain objects.

Design notes:
- Accepts a list of Holding objects (from one or more accounts).
- Computes all aggregate fields (totals, sector weights, concentration flags).
- Never stores raw holdings in the snapshot — aggregates only.
- Snapshot is written to storage via SnapshotRepository.
- Once written, a snapshot is never mutated (frozen Pydantic model).

IMPORTANT: Do NOT import from agents/, core/, or pages/.
"""

from __future__ import annotations

# from ori_commercial_v0.domain.models import Holding, PortfolioSnapshot


def build_snapshot(
    client_id: str,
    holdings: list,          # list[Holding] — typed when implemented
    risk_profile=None,       # Optional[RiskProfile]
) -> dict:                   # PortfolioSnapshot when implemented
    """
    Build a PortfolioSnapshot from a client's current holdings.

    Parameters
    ----------
    client_id : str
    holdings : list[Holding]
        All holdings across all of the client's accounts.
    risk_profile : RiskProfile, optional
        If provided, risk_score and risk_tolerance are included in the snapshot.

    Returns
    -------
    PortfolioSnapshot
        Frozen, immutable aggregate.  Never contains raw row-level data.

    Implementation notes (for future dev):
    1. Group holdings by symbol — compute per-symbol market_value, weight_pct,
       cost_basis, unrealized_gain.
    2. Aggregate to portfolio level: total_market_value, total_cost_basis, etc.
    3. Compute account-type split: registered_value, non_registered_value,
       unclassified_value.
    4. Compute sector_weights_pct from per-holding sector + market_value.
    5. Populate concentration_flags from risk_profile.max_single_position_pct.
    6. Construct and return a frozen PortfolioSnapshot.
    """
    raise NotImplementedError("snapshot_builder is a stub — implement in a future phase.")
