# Auri Retirement Planner Agent — Architecture Design
**Status:** Design / Pre-implementation
**Date:** March 2026
**Inspired by:** Conquest Planning (Canadian financial planning platform)

---

## Vision

A dedicated retirement planning agent within Auri that models the investor's full financial picture over time — not just what the portfolio is worth today, but whether it will last, how to draw it down efficiently, and what the tax consequences are along the way.

The four pillars mirror Conquest's core workflow:
1. **Scenario comparison** — model multiple futures side by side
2. **Tax efficiency** — withdrawal sequencing, TFSA/RRSP/non-reg optimization, CPP/OAS timing
3. **Compliance and reporting** — RRSP deduction limits, TFSA room tracking, CRA rule adherence
4. **Client engagement** — visuals designed to make 30-year projections feel concrete

---

## Agent Design

### Agent name: `ori_rp` (ORI Retirement Planner)

Follows the same architecture pattern as `ori_ia`:
- Pure analytics functions (no I/O, no side effects) in `analytics.py`
- File I/O and job routing in `core/job_runner.py` action handlers
- Streamlit UI in `pages/6_Retirement.py`
- All personal financial data stays local and gitignored

---

## Pillar 1 — Scenario Comparison

### Core concept
The planner builds a year-by-year cash flow model from retirement start (or today if already retired) through age 95 (or user-defined end). Each scenario is a complete parameterized run of the model.

### Parameters per scenario
```
{
  name:                    str        e.g. "Base Case", "Early Retirement", "Market Stress"
  retirement_age:          int        when drawdown begins
  target_annual_spending:  float      real dollars, today's purchasing power
  inflation_rate_pct:      float      default 2.5%
  portfolio_return_pct:    float      real expected net return (after fees)
  cpp_start_age:           int        60–70; affects monthly benefit
  oas_start_age:           int        65–70; deferral increases benefit
  part_time_income:        float      optional: bridge income before full retirement
  large_expenditures:      [{year, amount}]  home reno, vehicle, travel
  longevity_age:           int        planning horizon (default 95)
}
```

### Outputs per year
- Portfolio value (registered, non-registered, TFSA separate)
- Annual withdrawals by account type
- Annual taxes paid (estimated)
- Annual surplus / shortfall
- Real spending power delivered

### Scenario comparison view
Side-by-side chart of portfolio balance over time for up to 4 scenarios. Visual emphasis on:
- Year portfolio runs out (if ever) — the number clients most want to know
- Annual tax load by scenario
- CPP/OAS timing impact

### Monte Carlo overlay (Phase 2)
- Run 500 simulations per scenario with randomized annual returns drawn from a normal distribution (μ = scenario return, σ = historical volatility for the asset mix)
- Show P10, P50, P90 bands on the portfolio value chart
- "Probability of not running out" at planning horizon

---

## Pillar 2 — Tax Efficiency

### 2.1 Withdrawal sequencing

Canadian tax-optimal drawdown order is not obvious and is highly personal. The planner should model and compare:

**Conservative sequence (minimize current taxes):**
1. Non-registered (capital gains only — half inclusion rate)
2. RRSP/RRIF (fully taxable)
3. TFSA last (tax-free, preserve for legacy or longevity)

**Income-bracket optimization:**
- Fill each tax bracket to its ceiling before moving to the next account type
- Model OAS clawback threshold ($90,997 in 2025): avoid triggering clawback by managing RRIF minimums

**RRSP meltdown strategy:**
- Accelerate RRSP withdrawals in low-income years (e.g., before CPP/OAS start, or before RRIF conversion at 71)
- Compare: withdraw early at 25% marginal vs. withdraw at 40%+ marginal during peak income years

### 2.2 TFSA optimization
- Model TFSA contribution room (cumulative since 2009 minus prior withdrawals)
- Suggest re-contribution strategy after non-reg withdrawals
- Prioritize highest-growth positions inside TFSA (tax-free compounding)

### 2.3 CPP/OAS timing
- CPP: each year deferred from 60→70 increases benefit ~8.4%/year (actuarial adjustment)
- OAS: each year deferred from 65→70 increases benefit 7.2%/year
- Model break-even age: at what longevity does deferral pay off?
- Show as a simple chart: cumulative CPP income by start age through age 95

### 2.4 Income splitting
- Pension income splitting (eligible pension income can be split with spouse)
- RRSP spousal contributions for future income splitting
- Model family unit tax vs. individual if profile includes a spouse

### Tax estimation approach
Use marginal federal + provincial tax brackets (hardcoded, updated annually). Not a tax filing tool — estimates only. Prominently disclaim that CRA rules should be verified with a tax professional.

---

## Pillar 3 — Compliance and Reporting

### 3.1 RRSP / RRIF rules
- RRSP contribution limit: 18% of prior-year earned income, max $31,560 (2025)
- RRSP must convert to RRIF by Dec 31 of year turning 71
- RRIF minimum withdrawals by age (CRA table — load from local YAML, updated annually)
- Alert when model forces RRIF minimums to exceed the investor's spending need (excess accumulates in taxable accounts — often overlooked)

### 3.2 TFSA tracking
- Annual contribution room: $7,000 (2025), indexed to inflation
- Track cumulative room from profile's TFSA start year
- Warn on over-contribution risk when suggesting re-contribution

### 3.3 OAS clawback
- 2025 threshold: $90,997
- Clawback rate: 15% on income above threshold
- Full clawback at ~$148,065
- Flag in model when withdrawal plan triggers clawback
- Suggest mitigation: TFSA drawdown, income splitting, charitable giving

### 3.4 Reports
- **One-page summary:** scenario selected, portfolio longevity, annual withdrawal plan for next 5 years (account by account), tax estimate, key risks
- **Annual review checklist:** TFSA room check, RRSP deadline reminder, RRIF minimum due, OAS clawback exposure
- Export as PDF (Phase 2 — use `reportlab` or `weasyprint`)

---

## Pillar 4 — Client Engagement (Visuals)

Conquest's differentiator is making 30-year projections feel real and understandable. Key visual principles:

### 4.1 The "Will I run out?" chart
- Primary chart: portfolio value by year, three scenarios overlaid
- Horizontal zero line clearly marked
- Year-of-depletion highlighted as a vertical marker if applicable
- P10/P50/P90 bands in Monte Carlo mode
- Call-out: "At your current spending rate, your portfolio lasts to age [X]"

### 4.2 Income waterfall
- Stacked bar chart per year: CPP | OAS | Part-time | Portfolio withdrawal
- Target spending line overlaid
- Colour-coded by income source (government vs portfolio)
- Shows the "income gap" that must come from portfolio

### 4.3 Tax burden timeline
- Annual tax estimate as a line chart over retirement
- Highlights RRIF conversion year
- Shows OAS clawback impact years (if any)

### 4.4 Account balance projection
- Stacked area chart: TFSA / RRSP-RRIF / Non-registered separately
- Shows the "bucket depletion" sequence visually
- Helps investor understand which bucket disappears first and why

### 4.5 CPP/OAS timing comparison
- Simple table + bar chart: monthly benefit vs. break-even age for 5 start-age options
- "If you live to 85, starting CPP at 65 vs 70 means $X more lifetime income"

### 4.6 Spending dial
- Large, prominent metric at the top of the page: "You can sustainably spend $[X]/year"
- Based on the 90% probability of success scenario
- Updates dynamically when scenario parameters change

---

## Data Model

### Input: `retirement_profile.yaml` (gitignored)

Household section included from Phase 1 — avoids painful schema migration in Phase 4.
Even single-person plans should populate the `household.primary` block; `spouse` is omitted when not applicable.

```yaml
# Personal data — never committed to git
version: "1.0"
owner: "jeff"

household:
  primary:
    current_age:              65
    province:                 "ON"      # for provincial tax brackets
    cpp_monthly_at_65:        1200.00   # from My Service Canada account
    oas_monthly_at_65:         700.00
    pension_monthly:             0.0    # defined benefit pension if any
    rrsp_rrif_balance:       450000.00
    tfsa_balance:             95000.00
    non_registered_balance:  180000.00
    tfsa_room_remaining:      28000.00
    tfsa_start_year:            2009    # year first eligible; determines cumulative room
    part_time_income:            0.0
    part_time_until_age:         0      # 0 = no part-time bridge

  spouse:                               # omit entire block if no spouse
    current_age:              62
    province:                 "ON"
    cpp_monthly_at_65:         900.00
    oas_monthly_at_65:         650.00
    pension_monthly:             0.0
    rrsp_rrif_balance:       120000.00
    tfsa_balance:              45000.00
    non_registered_balance:   30000.00
    tfsa_room_remaining:       20000.00
    tfsa_start_year:            2009
    part_time_income:            0.0
    part_time_until_age:         0

spending:
  annual_target:              80000.00  # household total, today's dollars
  inflation_rate_pct:            2.5
  large_expenditures:
    - {year: 2026, amount: 50000, label: "Home renovation"}
    - {year: 2030, amount: 35000, label: "Vehicle replacement"}
```

### Reference data: `refs/retirement/` (tracked in git, updated annually)

```
refs/retirement/
  tax_brackets_2026.yaml      — federal + per-province marginal brackets
  rrif_minimums.yaml          — CRA RRIF minimum withdrawal % by age
  cpp_adjustments.yaml        — actuarial adjustment factors by start age (60–70)
  oas_adjustments.yaml        — deferral increase factors (65–70)
  tfsa_room_by_year.yaml      — annual TFSA limit by calendar year (2009–present)
```

Example `tax_brackets_2026.yaml` structure:
```yaml
year: 2026
federal:
  brackets:
    - {min: 0,       max: 57375,  rate: 15.0}
    - {min: 57375,   max: 114750, rate: 20.5}
    - {min: 114750,  max: 158519, rate: 26.0}
    - {min: 158519,  max: 220000, rate: 29.0}
    - {min: 220000,  max: null,   rate: 33.0}
  basic_personal_amount: 16129
  oas_clawback_threshold: 93454
  oas_clawback_rate: 0.15

provincial:
  ON:
    brackets:
      - {min: 0,      max: 51446,  rate: 5.05}
      - {min: 51446,  max: 102894, rate: 9.15}
      - {min: 102894, max: 150000, rate: 11.16}
      - {min: 150000, max: 220000, rate: 12.16}
      - {min: 220000, max: null,   rate: 13.16}
    basic_personal_amount: 11865
  BC:
    # ... same structure
  AB:
    # ... same structure
```

This approach means annual January tax updates require only editing one YAML file — no code changes.

### Output: `data/retirement/` (gitignored)

Scenario files named `{scenario_name}_{YYYY-MM-DD}.json` to support loading previous runs for comparison.

```
data/retirement/
  scenarios/
    base_2026-03-06.json
    early_retirement_2026-03-06.json
    conservative_2026-03-06.json
  reports/
    annual_review_2026-03.md
```

Scenario JSON structure:
```json
{
  "scenario_name":  "base",
  "generated_at":   "2026-03-06T14:32:00",
  "parameters":     { ... scenario inputs ... },
  "disclaimer":     "Estimates only. Consult your tax advisor and investment professional before acting on any projection in this report.",
  "cash_flows": [
    {
      "year": 2026, "age_primary": 65, "age_spouse": 62,
      "portfolio_value": 725000.00,
      "cpp_income": 14400.00, "oas_income": 8400.00,
      "portfolio_withdrawal": 57200.00,
      "taxes_estimated": 8800.00,
      "spending_delivered": 80000.00,
      "surplus_shortfall": 0.0,
      "rrsp_rrif_balance": 420000.00,
      "tfsa_balance": 102000.00,
      "non_reg_balance": 185000.00
    }
  ]
}
```

---

## Implementation Phases

### Phase 1 — Core model + basic scenarios (builds on existing work)
- `agents/ori_rp/cashflow.py` — year-by-year projection engine
- `agents/ori_rp/tax.py` — Canadian federal + ON provincial brackets, RRIF minimums
- `agents/ori_rp/cpp_oas.py` — CPP/OAS benefit calculation by start age
- `pages/6_Retirement.py` — basic scenario builder UI
- Three hardcoded scenarios: Base Case, Conservative, Optimistic
- "Will I run out?" chart + spending dial

### Phase 2 — Tax optimization + compliance
- Withdrawal sequencing engine
- RRSP meltdown modelling
- OAS clawback detection
- TFSA room tracking
- Scenario: "Tax-optimized withdrawal order"

### Phase 3 — Monte Carlo + reporting
- Monte Carlo simulation using `numpy.random.normal(mu=scenario_return, sigma=portfolio_volatility, size=500)`
  - Volatility by asset mix: conservative ~8%, balanced ~12%, growth ~15%, aggressive ~18%
  - Each run applies a geometric return sequence: `balance *= (1 + r/100)` year by year
  - Optional: geometric Brownian motion (`numpy.random.lognormal`) for more realistic fat-tail behaviour
- P10/P50/P90 confidence bands on the "Will I run out?" chart
- Probability of success at planning horizon: `sum(1 for r in runs if r[-1] > 0) / len(runs)`
- PDF one-page summary report (via `reportlab` or `weasyprint`)
- Annual review checklist page

### Phase 4 — Spouse/household and integration
- Household mode: model two individuals, income splitting
- Link to portfolio agent: feed actual portfolio MV + asset mix into return assumption
- Retirement readiness score (0–100) integrated on Home page

---

## Key Constraints

1. **All computation is local.** No network calls for projections — purely deterministic (Phase 1-2) or locally seeded random (Phase 3).

2. **Tax estimates are approximate, not CRA authoritative.** Tax brackets are stored in `refs/retirement/tax_brackets_{year}.yaml` and updated each January. The tool must clearly disclaim these are estimates and recommend professional advice for actual filing.

3. **No personal data in snapshots or git.** `retirement_profile.yaml` and all scenario outputs go in gitignored directories. `refs/retirement/` (public CRA data) is tracked in git.

4. **Separation from portfolio agent.** Phase 1 uses manually entered account balances (retirement_profile.yaml). Phase 4 integrates with ori_ia portfolio data. This keeps the agents independently usable.

5. **Household schema in Phase 1.** The `household.primary` / `household.spouse` structure is included from the start to avoid schema migration in Phase 4. Single-person plans leave the `spouse` block absent; the cashflow engine handles both cases.

---

## Disclaimers

Every page, report, and exported scenario must display prominently:

> **These projections are estimates only. Tax calculations use simplified marginal brackets and do not account for all deductions, credits, or personal circumstances. Consult your tax advisor, financial planner, and investment professional before acting on any projection in this tool. CPP and OAS benefit calculations are illustrative — use your My Service Canada statement for accurate figures.**

The disclaimer is embedded in:
- The Streamlit page caption on `pages/6_Retirement.py`
- Every generated scenario JSON (`disclaimer` field at the top level)
- Every generated report markdown file (first and last line)
- Every exported PDF (footer on each page)

---

## Reference: Conquest Planning Capabilities to Mirror

| Conquest Feature                          | Auri Phase |
|-------------------------------------------|-----------|
| Scenario comparison (up to 4 scenarios)   | Phase 1   |
| Net worth projection chart                | Phase 1   |
| Income sources waterfall                  | Phase 1   |
| CPP/OAS optimization                      | Phase 1   |
| Withdrawal sequencing                     | Phase 2   |
| RRSP meltdown strategy                    | Phase 2   |
| OAS clawback modelling                    | Phase 2   |
| Monte Carlo probability analysis          | Phase 3   |
| PDF plan summary report                   | Phase 3   |
| Household / couples mode                  | Phase 4   |
| Portfolio integration (live MV)           | Phase 4   |

---

*This document captures the architectural intent. Implementation begins with Phase 1 cashflow engine and basic UI. Each phase builds on the previous without breaking existing functionality.*
