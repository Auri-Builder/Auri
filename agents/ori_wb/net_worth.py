"""
agents/ori_wb/net_worth.py
--------------------------
Net worth balance sheet computation.

Assets:
  Registered   — RRSP/RRIF, TFSA, pension (commuted value estimate)
  Non-registered — taxable investment accounts
  Real estate  — primary residence, rental, other property
  Vehicles     — car, boat, other depreciating assets
  Other        — business equity, receivables, valuables

Liabilities:
  Mortgage(s), HELOC, car loans, student loans, personal loans,
  credit card balances, other debts

Net Worth = Total Assets − Total Liabilities

The module also computes a simple "wealth snapshot" score and commentary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class AssetItem:
    label:      str
    value:      float
    category:   str   # registered / non_reg / real_estate / vehicle / other


@dataclass
class LiabilityItem:
    label:      str
    balance:    float
    rate_pct:   float = 0.0   # interest rate for debt-cost display


@dataclass
class NetWorthInput:
    assets:      list[AssetItem]      = field(default_factory=list)
    liabilities: list[LiabilityItem]  = field(default_factory=list)


@dataclass
class CategorySummary:
    category:  str
    label:     str
    total:     float
    pct_of_assets: float


@dataclass
class NetWorthResult:
    total_assets:        float
    total_liabilities:   float
    net_worth:           float
    asset_categories:    list[CategorySummary]
    debt_cost_annual:    float   # estimated annual interest across all liabilities
    leverage_ratio:      float   # liabilities / assets (0 = debt-free, >0.5 = high leverage)
    commentary:          str


_CATEGORY_LABELS = {
    "registered":   "Registered Accounts (RRSP/TFSA/Pension)",
    "non_reg":      "Non-Registered Investments",
    "real_estate":  "Real Estate",
    "vehicle":      "Vehicles",
    "other":        "Other Assets",
}


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def compute_net_worth(inp: NetWorthInput) -> NetWorthResult:
    """Compute net worth balance sheet from assets and liabilities."""
    total_assets      = sum(a.value for a in inp.assets)
    total_liabilities = sum(l.balance for l in inp.liabilities)
    net_worth         = total_assets - total_liabilities
    debt_cost         = sum(l.balance * l.rate_pct / 100.0 for l in inp.liabilities)

    leverage = (total_liabilities / total_assets) if total_assets > 0 else 0.0

    # ── Asset category breakdown ───────────────────────────────────────────
    cat_totals: dict[str, float] = {}
    for a in inp.assets:
        cat_totals[a.category] = cat_totals.get(a.category, 0.0) + a.value

    asset_categories: list[CategorySummary] = []
    for cat in ("registered", "non_reg", "real_estate", "vehicle", "other"):
        val = cat_totals.get(cat, 0.0)
        if val > 0:
            asset_categories.append(CategorySummary(
                category       = cat,
                label          = _CATEGORY_LABELS.get(cat, cat),
                total          = val,
                pct_of_assets  = (val / total_assets * 100.0) if total_assets > 0 else 0.0,
            ))

    # ── Commentary ────────────────────────────────────────────────────────
    commentary = _generate_commentary(net_worth, total_assets, leverage, debt_cost, inp)

    return NetWorthResult(
        total_assets       = total_assets,
        total_liabilities  = total_liabilities,
        net_worth          = net_worth,
        asset_categories   = asset_categories,
        debt_cost_annual   = debt_cost,
        leverage_ratio     = leverage,
        commentary         = commentary,
    )


def _generate_commentary(
    net_worth: float,
    total_assets: float,
    leverage: float,
    debt_cost: float,
    inp: NetWorthInput,
) -> str:
    lines: list[str] = []

    if net_worth < 0:
        lines.append("Your liabilities currently exceed your assets. Focus on debt reduction before accelerating investments.")
    elif leverage > 0.6:
        lines.append("Leverage is high — over 60% of your assets are debt-financed. Prioritise paying down high-rate debt.")
    elif leverage > 0.3:
        lines.append("Moderate leverage. Maintaining a balance between debt repayment and investing is appropriate.")
    else:
        lines.append("Healthy balance sheet — leverage is low.")

    reg_total = sum(a.value for a in inp.assets if a.category == "registered")
    if total_assets > 0:
        reg_pct = reg_total / total_assets * 100.0
        if reg_pct < 20.0 and total_assets > 50_000:
            lines.append(f"Only {reg_pct:.0f}% of assets are in registered accounts — maximising RRSP/TFSA room could improve tax efficiency.")
        elif reg_pct > 80.0:
            lines.append(f"Most assets ({reg_pct:.0f}%) are in registered accounts — good tax sheltering.")

    re_total = sum(a.value for a in inp.assets if a.category == "real_estate")
    if total_assets > 0 and re_total / total_assets > 0.7:
        lines.append("Real estate represents over 70% of total assets — consider whether investment portfolio diversification is needed.")

    if debt_cost > 10_000:
        lines.append(f"Estimated annual interest cost: ${debt_cost:,.0f} — reducing high-rate debt delivers a guaranteed after-tax return.")

    return " ".join(lines) if lines else "Balance sheet looks solid."
