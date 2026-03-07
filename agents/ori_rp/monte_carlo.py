"""
agents/ori_rp/monte_carlo.py
------------------------------
Monte Carlo retirement simulation — Phase 3.

Approach
--------
Running the full cashflow engine 500 times would be slow because each call
invokes tax estimation, withdrawal sequencing, and CPP/OAS adjustments per year.
Instead we use a two-pass approach that is fast and still credible:

  Pass 1 (deterministic spine):
    Run project_scenario() once to get year-by-year spending needs, government
    income, taxes, and the starting balances. These are treated as fixed cash
    outflows in every simulation — only the portfolio return varies.

  Pass 2 (Monte Carlo):
    For each of N simulations, draw an independent sequence of annual returns
    from Normal(mu=scenario_return, sigma=asset_mix_volatility).
    Apply each return to the running balance, then subtract the deterministic
    net withdrawal (spending + taxes - government income).

    If the balance hits zero, the portfolio is depleted — record the year.

This matches industry practice: the "Monte Carlo" part is the return uncertainty,
not re-running the full tax engine 500 times.

Return sequence model
---------------------
We use numpy.random.normal (arithmetic returns, applied geometrically):
    balance *= (1 + r / 100)
    balance -= net_outflow

A lognormal alternative is noted in the architecture doc as a Phase 3+ option.
It is easily swapped in by changing _sample_returns() — the rest of the engine
does not change.

Volatility source
-----------------
Loaded from refs/retirement/volatility.yaml — Conservative 8%, Balanced 12%,
Growth 15%, Aggressive 18%. The caller selects asset_mix from this file.

Outputs
-------
dict:
    ages             : list[int]    — age of primary person per projection year
    p10              : list[float]  — 10th percentile portfolio value by year
    p50              : list[float]  — median portfolio value by year
    p90              : list[float]  — 90th percentile portfolio value by year
    prob_success     : float        — fraction of sims with portfolio > 0 at longevity_age
    depletion_ages   : list[int]    — depletion age per sim (None if not depleted)
    n_sims           : int
    asset_mix        : str
    sigma_used       : float
    mu_used          : float
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_REFS_DIR = Path(__file__).parent.parent.parent / "refs" / "retirement"


# ---------------------------------------------------------------------------
# Volatility table
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_volatility() -> dict[str, float]:
    """Load asset mix volatility table {mix_name: sigma_pct}."""
    import yaml
    path = _REFS_DIR / "volatility.yaml"
    with path.open() as f:
        data = yaml.safe_load(f)
    return {k: float(v) for k, v in data["volatility"].items()}


def asset_mix_options() -> list[str]:
    """Return available asset mix names from volatility.yaml."""
    return list(_load_volatility().keys())


def sigma_for_mix(asset_mix: str) -> float:
    """Return standard deviation (%) for the given asset mix label."""
    table = _load_volatility()
    # Case-insensitive match
    for k, v in table.items():
        if k.lower() == asset_mix.lower():
            return v
    raise ValueError(f"Unknown asset mix '{asset_mix}'. Available: {list(table.keys())}")


# ---------------------------------------------------------------------------
# Return sampling
# ---------------------------------------------------------------------------

def _sample_returns(
    mu:    float,   # expected annual return %
    sigma: float,   # standard deviation %
    n_sims: int,
    n_years: int,
    seed: int | None,
) -> "numpy.ndarray":   # shape (n_sims, n_years)
    """
    Draw a (n_sims × n_years) matrix of annual returns using Normal(mu, sigma).
    Returns are in percent (e.g. 5.0 = +5%).
    """
    import numpy as np
    rng = np.random.default_rng(seed)
    return rng.normal(loc=mu, scale=sigma, size=(n_sims, n_years))


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def run_monte_carlo(
    deterministic_rows: list,   # list[YearResult] from project_scenario()
    mu:     float,              # scenario portfolio_return_pct
    asset_mix: str = "Balanced",
    n_sims: int    = 500,
    seed:   int | None = None,
) -> dict:
    """
    Run a Monte Carlo simulation over the deterministic cashflow spine.

    Parameters
    ----------
    deterministic_rows : Output of project_scenario() for the chosen scenario.
    mu                 : Expected annual return % (from ScenarioParams.portfolio_return_pct).
    asset_mix          : Asset mix label matching a key in volatility.yaml.
    n_sims             : Number of simulations (default 500).
    seed               : Random seed for reproducibility (None = random).

    Returns
    -------
    See module docstring.
    """
    import numpy as np

    sigma    = sigma_for_mix(asset_mix)
    n_years  = len(deterministic_rows)
    ages     = [r.age_primary for r in deterministic_rows]

    # Starting portfolio = total household balance at start of year 0 (before growth/withdrawal)
    initial_portfolio = deterministic_rows[0].portfolio_start

    # Deterministic net outflow each year: spending + taxes - government income
    # (already computed in the cashflow engine — we just read it back)
    net_outflows = []
    for r in deterministic_rows:
        government_in = r.cpp_income + r.oas_income + r.pension_income + r.part_time_income
        outflow       = r.spending_target + r.large_expenditure + r.taxes_estimated - government_in
        net_outflows.append(max(0.0, outflow))  # can't have negative outflow (surplus stays in portfolio)

    net_outflows_arr = np.array(net_outflows)

    # Sample return matrix
    returns = _sample_returns(mu, sigma, n_sims, n_years, seed)  # (n_sims, n_years)

    # Vectorized simulation: shape (n_sims, n_years+1)
    # Column 0 = start-of-year-0 balance (before any growth/withdrawal)
    balances = np.zeros((n_sims, n_years + 1))
    balances[:, 0] = initial_portfolio

    for yr in range(n_years):
        growth   = balances[:, yr] * (returns[:, yr] / 100.0)
        new_bal  = balances[:, yr] + growth - net_outflows_arr[yr]
        balances[:, yr + 1] = np.maximum(new_bal, 0.0)

    # End-of-year balances (columns 1..n_years)
    end_balances = balances[:, 1:]   # shape (n_sims, n_years)

    # Percentile bands by year
    p10 = np.percentile(end_balances, 10, axis=0).tolist()
    p50 = np.percentile(end_balances, 50, axis=0).tolist()
    p90 = np.percentile(end_balances, 90, axis=0).tolist()

    # Probability of success: portfolio > 0 at final year
    final_balances   = end_balances[:, -1]
    prob_success     = float(np.mean(final_balances > 0))

    # Depletion age per simulation
    depletion_ages: list[int | None] = []
    for sim_idx in range(n_sims):
        depleted = False
        for yr_idx in range(n_years):
            if end_balances[sim_idx, yr_idx] <= 0:
                depletion_ages.append(ages[yr_idx])
                depleted = True
                break
        if not depleted:
            depletion_ages.append(None)

    # Depletion age histogram (for the UI)
    depleted_sims    = [a for a in depletion_ages if a is not None]
    depletion_pct    = len(depleted_sims) / n_sims

    # Sustainable spending estimate: spending at P50 that keeps portfolio > 0
    # (Phase 3 metric — simple: the spending in the deterministic spine that the
    # median sim can sustain. Reported as the target from the scenario.)
    spending_target  = net_outflows_arr[0] + (
        deterministic_rows[0].cpp_income +
        deterministic_rows[0].oas_income +
        deterministic_rows[0].pension_income
    ) if deterministic_rows else 0.0

    return {
        "ages":             ages,
        "p10":              [round(v, 2) for v in p10],
        "p50":              [round(v, 2) for v in p50],
        "p90":              [round(v, 2) for v in p90],
        "prob_success":     round(prob_success * 100, 1),   # percent, e.g. 87.4
        "depletion_ages":   depletion_ages,
        "depletion_pct":    round(depletion_pct * 100, 1),  # percent depleted
        "median_depletion_age": (
            int(sorted(depleted_sims)[len(depleted_sims) // 2]) if depleted_sims else None
        ),
        "n_sims":           n_sims,
        "asset_mix":        asset_mix,
        "sigma_used":       sigma,
        "mu_used":          mu,
    }


# ---------------------------------------------------------------------------
# Depletion age histogram data (for chart)
# ---------------------------------------------------------------------------

def depletion_histogram(mc_result: dict) -> dict:
    """
    Compute a histogram of depletion ages from Monte Carlo results.

    Returns dict suitable for a bar chart:
        ages   : list[int]  — age buckets (5-year bands)
        counts : list[int]  — number of simulations depleted in that band
    """
    depleted = [a for a in mc_result["depletion_ages"] if a is not None]
    if not depleted:
        return {"ages": [], "counts": [], "labels": []}

    age_min = min(depleted)
    age_max = max(depleted)
    buckets: dict[int, int] = {}
    for age in range(age_min, age_max + 1):
        buckets[age] = 0
    for age in depleted:
        buckets[age] = buckets.get(age, 0) + 1

    ages   = sorted(buckets.keys())
    counts = [buckets[a] for a in ages]
    return {"ages": ages, "counts": counts}
