"""
agents/ori_wb/projector.py
--------------------------
Savings rate → Financial Independence (FI) number → retirement age projector.

Computes year-by-year wealth accumulation given:
  - current age and savings balance
  - annual income and savings rate (%)
  - expected nominal return and inflation
  - FI target multiple (default 25× annual spending, i.e. 4% SWR)

Outputs:
  - Year-by-year projection table
  - Projected nest egg at target retirement age
  - FI age (first year balance ≥ FI number)
  - Sensitivity table: ±1% return, ±2% savings rate scenarios

Disclaimer: Projections assume constant return and savings; actual markets
fluctuate. This is a planning tool, not a guarantee of outcomes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ProjectorInput:
    current_age:          int
    current_savings:      float          # total investable assets today ($)
    annual_income:        float          # gross employment income
    savings_rate_pct:     float          # % of gross income saved per year (e.g. 20.0)
    expected_return_pct:  float = 6.0   # nominal annual return (%)
    inflation_pct:        float = 2.5   # annual inflation (%)
    target_retirement_age: int  = 65    # user's goal age
    fi_multiple:          float = 25.0  # FI = fi_multiple × annual spending
    # annual spending derived as income × (1 - savings_rate/100) if not provided
    annual_spending:      float = 0.0   # override; 0 = derive from income + savings rate


@dataclass
class YearRow:
    age:          int
    year:         int
    contributions: float
    balance:      float
    fi_number:    float
    on_track:     bool   # balance ≥ fi_number


@dataclass
class ProjectorResult:
    rows:                  list[YearRow]
    fi_age:                int | None     # None = not reached within projection
    balance_at_target:     float
    fi_number_at_target:   float
    shortfall_at_target:   float          # negative = surplus
    savings_rate_pct:      float
    annual_contribution:   float
    sensitivity:           list[dict]     # scenario rows for sensitivity table


# ---------------------------------------------------------------------------
# Core projection
# ---------------------------------------------------------------------------

def project(inp: ProjectorInput, _include_sensitivity: bool = True) -> ProjectorResult:
    """Run year-by-year accumulation projection."""
    r       = inp.expected_return_pct / 100.0
    inf     = inp.inflation_pct / 100.0
    savings = max(0.0, inp.savings_rate_pct / 100.0)

    annual_spending = inp.annual_spending if inp.annual_spending > 0 else (
        inp.annual_income * (1.0 - savings)
    )
    annual_contribution = inp.annual_income * savings

    current_year = 2026  # base year

    rows: list[YearRow] = []
    balance  = inp.current_savings
    fi_age   = None

    # Project to max(target_retirement_age, 75) to show the full arc
    end_age = max(inp.target_retirement_age, 75)

    for age in range(inp.current_age, end_age + 1):
        year = current_year + (age - inp.current_age)
        # FI number grows with inflation so that purchasing power is preserved
        inflation_factor = (1.0 + inf) ** (age - inp.current_age)
        fi_number = annual_spending * inp.fi_multiple * inflation_factor

        on_track = balance >= fi_number
        if on_track and fi_age is None:
            fi_age = age

        rows.append(YearRow(
            age           = age,
            year          = year,
            contributions = annual_contribution,
            balance       = round(balance, 2),
            fi_number     = round(fi_number, 2),
            on_track      = on_track,
        ))

        # End of year: add contributions then apply return
        balance = (balance + annual_contribution) * (1.0 + r)

    target_row = next((row for row in rows if row.age == inp.target_retirement_age), rows[-1])
    fi_at_target = target_row.fi_number

    sensitivity = _sensitivity_table(inp) if _include_sensitivity else []

    return ProjectorResult(
        rows                  = rows,
        fi_age                = fi_age,
        balance_at_target     = target_row.balance,
        fi_number_at_target   = fi_at_target,
        shortfall_at_target   = fi_at_target - target_row.balance,
        savings_rate_pct      = inp.savings_rate_pct,
        annual_contribution   = annual_contribution,
        sensitivity           = sensitivity,
    )


def _sensitivity_table(inp: ProjectorInput) -> list[dict]:
    """Return sensitivity rows varying return and savings rate."""
    base_return  = inp.expected_return_pct
    base_savings = inp.savings_rate_pct
    scenarios = [
        ("Base case",            base_return,      base_savings),
        ("Return −1%",           base_return - 1,  base_savings),
        ("Return +1%",           base_return + 1,  base_savings),
        ("Save 2% less",         base_return,      max(0, base_savings - 2)),
        ("Save 2% more",         base_return,      base_savings + 2),
        ("Pessimistic",          base_return - 1,  max(0, base_savings - 2)),
        ("Optimistic",           base_return + 1,  base_savings + 2),
    ]
    rows = []
    for label, ret, sav in scenarios:
        alt = ProjectorInput(
            current_age           = inp.current_age,
            current_savings       = inp.current_savings,
            annual_income         = inp.annual_income,
            savings_rate_pct      = sav,
            expected_return_pct   = ret,
            inflation_pct         = inp.inflation_pct,
            target_retirement_age = inp.target_retirement_age,
            fi_multiple           = inp.fi_multiple,
            annual_spending       = inp.annual_spending,
        )
        result = project(alt, _include_sensitivity=False)
        rows.append({
            "scenario":          label,
            "return_pct":        ret,
            "savings_rate_pct":  sav,
            "balance_at_target": result.balance_at_target,
            "fi_number":         result.fi_number_at_target,
            "shortfall":         result.shortfall_at_target,
            "fi_age":            result.fi_age,
        })
    return rows
