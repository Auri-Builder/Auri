"""
ori_commercial_v0/domain/models.py
───────────────────────────────────
Canonical domain model for ORI Commercial.

All external data (CRM, custodian, documents) is translated into these
types before it enters the system.  Downstream code — engines, AI
orchestrator, storage — must only consume these types, never raw external
data.

Design principles:
- Pydantic v2 with strict mode (no silent type coercion).
- Immutable where it matters: Snapshot is frozen.
- All monetary values are float (CAD unless otherwise noted).
  A future revision will use Decimal for ledger precision.
- IDs are str (UUIDs in practice) to avoid int/UUID impedance mismatch.
- No business logic in domain models — that belongs in the engines.

IMPORTANT: Do NOT import from agents/, core/, or pages/.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AccountType(str, Enum):
    TFSA       = "TFSA"
    RRSP       = "RRSP"
    RRIF       = "RRIF"
    FHSA       = "FHSA"
    RESP       = "RESP"
    CASH       = "CASH"       # non-registered cash/margin
    CORPORATE  = "CORPORATE"  # corporate account
    OTHER      = "OTHER"


class AssetClass(str, Enum):
    EQUITY        = "Equity"
    FIXED_INCOME  = "Fixed Income"
    CASH_EQUIV    = "Cash Equivalent"
    REAL_ESTATE   = "Real Estate"
    ALTERNATIVE   = "Alternative"
    OTHER         = "Other"


class RiskTolerance(str, Enum):
    CONSERVATIVE             = "conservative"
    MODERATELY_CONSERVATIVE  = "moderately_conservative"
    BALANCED                 = "balanced"
    GROWTH                   = "growth"
    AGGRESSIVE               = "aggressive"


class GoalType(str, Enum):
    CAPITAL_PRESERVATION = "capital_preservation"
    INCOME               = "income"
    BALANCED             = "balanced"
    GROWTH               = "growth"
    AGGRESSIVE_GROWTH    = "aggressive_growth"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class Client(BaseModel):
    """A single advisory client (individual or household)."""

    model_config = ConfigDict(strict=True, frozen=False)

    client_id:    str
    name:         str
    email:        Optional[str] = None
    advisor_id:   Optional[str] = None   # reference to advisor in CRM
    created_at:   Optional[date] = None
    metadata:     dict = Field(default_factory=dict)  # CRM passthrough fields


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------

class Account(BaseModel):
    """A single custodial account belonging to a client."""

    model_config = ConfigDict(strict=True, frozen=False)

    account_id:    str
    client_id:     str
    account_type:  AccountType
    institution:   str
    currency:      str = "CAD"
    is_registered: bool = False   # derived from account_type but stored for speed


# ---------------------------------------------------------------------------
# Holding
# ---------------------------------------------------------------------------

class Holding(BaseModel):
    """A single security position within an account at a point in time."""

    model_config = ConfigDict(strict=True, frozen=False)

    account_id:           str
    symbol:               str
    security_name:        Optional[str] = None
    quantity:             float
    market_price:         float
    market_value:         float
    cost_basis:           Optional[float] = None   # total position cost
    unrealized_gain:      Optional[float] = None
    asset_class:          Optional[AssetClass] = None
    sector:               Optional[str] = None     # GICS sector (future: enum)
    region:               Optional[str] = None     # geography (future: enum)
    as_of_date:           date


# ---------------------------------------------------------------------------
# RiskProfile
# ---------------------------------------------------------------------------

class RiskProfile(BaseModel):
    """Investor risk profile derived from a questionnaire or advisor input."""

    model_config = ConfigDict(strict=True, frozen=False)

    client_id:                     str
    risk_score:                    float               # 0–100
    risk_tolerance:                RiskTolerance
    primary_goal:                  GoalType
    time_horizon_years:            Optional[int] = None
    max_single_position_pct:       float = 20.0
    max_sector_pct:                float = 40.0
    max_drawdown_tolerance_pct:    Optional[float] = None
    excluded_sectors:              list[str] = Field(default_factory=list)
    completeness_pct:              float = 0.0          # questionnaire % complete
    scored_at:                     Optional[date] = None
    notes:                         Optional[str] = None


# ---------------------------------------------------------------------------
# IPS — Investment Policy Statement
# ---------------------------------------------------------------------------

class IPS(BaseModel):
    """
    Formalised Investment Policy Statement for a client.

    In v0 this is a lightweight representation.  A future phase will support
    full IPS document ingestion via DocumentConnector.
    """

    model_config = ConfigDict(strict=True, frozen=False)

    ips_id:               str
    client_id:            str
    effective_date:       date
    risk_profile:         RiskProfile
    target_return_pct:    Optional[float] = None
    benchmark:            Optional[str]   = None  # e.g. "60/40 ACWI/AGG"
    review_frequency:     str = "annual"          # annual | semi-annual | quarterly
    notes:                Optional[str]  = None


# ---------------------------------------------------------------------------
# Snapshot — IMMUTABLE
# ---------------------------------------------------------------------------

class PortfolioSnapshot(BaseModel):
    """
    Immutable, timestamped aggregate of a client's portfolio.

    Analytics engines and the AI orchestrator only ever receive a
    PortfolioSnapshot — never live holdings or account data.

    Design rule: once created, a snapshot is never mutated.
    Use frozen=True to enforce this at the Pydantic level.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    snapshot_id:           str
    client_id:             str
    created_at:            datetime

    # Portfolio-level aggregates
    total_market_value:    float
    total_cost_basis:      Optional[float] = None
    total_unrealized_gain: Optional[float] = None
    total_unrealized_gain_pct: Optional[float] = None
    account_count:         int
    position_count:        int

    # Account-type split (registered/non-registered/unclassified)
    registered_value:      float = 0.0
    non_registered_value:  float = 0.0
    unclassified_value:    float = 0.0

    # Per-symbol aggregates (no account-level detail — aggregates only)
    positions: list[dict] = Field(default_factory=list)

    # Sector weights
    sector_weights_pct: dict[str, float] = Field(default_factory=dict)

    # Risk context at snapshot time
    risk_score:        Optional[float]         = None
    risk_tolerance:    Optional[RiskTolerance] = None

    # IPS compliance flags (populated by risk_engine)
    concentration_flags: list[dict] = Field(default_factory=list)
    ips_violations:      list[dict] = Field(default_factory=list)
