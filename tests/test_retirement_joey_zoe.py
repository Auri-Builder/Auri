"""
tests/test_retirement_joey_zoe.py
----------------------------------
Test Case 1: Joey & Zoe Base Case — calibration test against a known
retirement scenario drawn from a planning video, adjusted for 2026
Canadian benefit rates.

Reference scenario
------------------
Two spouses, both age 64 retiring at 65, Ontario, no DB pension.
CPP at 70% of 2026 max ($1,507.65/mo → $1,055/mo each).
OAS at 2026 max for age 65-74 ($742/mo each).
Household spending $96,000/yr (today's $), 3% inflation.
Spending phases: slow-go at 75 (−18.75%), no-go at 85 (−7.69%).
Auto-shelter RRIF excess → TFSA enabled.
No bridge income, no DB pension, no one-time expenditures.

Balances
--------
Primary:  RRSP $350k  TFSA $100k  Non-Reg $100k
Spouse:   RRSP $350k  TFSA $100k  Non-Reg $0
Household portfolio: $1,000,000

Expected results (derived by running the engine — see assertions)
-----------------------------------------------------------------
Base Case (5% return, 3% inflation):
  avg_coverage_pct  = 100%          — fully funded to age 95
  depletion_age     = None          — portfolio never hits zero
  Estate at age 90  ≈ $700–800k    — comfortable surplus
  Year 1 (age 65):
    spending_target ≈ $98,880       — $96k × 1.03^1 (one year of inflation)
    cpp+oas income  ≈ $44,400       — both CPP + OAS from both spouses, inflated
    portfolio draw  ≈ $54,000       — entirely from RRIF (SIMPLE strategy)

Conservative (3.5% return, 3% inflation):
  avg_coverage_pct  ≈ 95–97%       — mirrors video's "94% on track" spirit
  depletion_age    ≈ 93–95         — runs low near planning horizon
  Estate at age 90  ≈ $50–200k     — thin but positive

Spending phase validation (Base Case):
  Age 74 spending target (no phase) < age 75 spending target (slow-go kicks in)
  slow-go reduction: spending at 75 is ~81.25% of what it would have been
  no-go further reduction: spending at 85 is ~92.31% of what it was at 84
"""

import pytest
from agents.ori_rp.cashflow import (
    PersonProfile, ScenarioParams, project_scenario, scenario_summary, YearResult
)
from agents.ori_rp.withdrawal import WithdrawalStrategy


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def primary() -> PersonProfile:
    return PersonProfile(
        current_age             = 64,
        rrsp_rrif_balance       = 350_000,
        tfsa_balance            = 100_000,
        non_registered_balance  = 100_000,
        cpp_monthly_at_65       = 1_055.0,
        oas_monthly_at_65       = 742.0,
        pension_monthly         = 0.0,
        pension_start_age       = 0,
        tfsa_room_remaining     = 0.0,
        part_time_income        = 0.0,
        part_time_until_age     = 0,
        province                = "ON",
    )


@pytest.fixture(scope="module")
def spouse() -> PersonProfile:
    return PersonProfile(
        current_age             = 64,
        rrsp_rrif_balance       = 350_000,
        tfsa_balance            = 100_000,
        non_registered_balance  = 0.0,
        cpp_monthly_at_65       = 1_055.0,
        oas_monthly_at_65       = 742.0,
        pension_monthly         = 0.0,
        pension_start_age       = 0,
        tfsa_room_remaining     = 0.0,
        part_time_income        = 0.0,
        part_time_until_age     = 0,
        province                = "ON",
    )


def _base_params(**overrides) -> ScenarioParams:
    """Return Base Case params with optional overrides."""
    defaults = dict(
        name                   = "Base Case",
        retirement_age         = 65,
        longevity_age          = 95,
        target_annual_spending = 96_000,
        inflation_rate_pct     = 3.0,
        portfolio_return_pct   = 5.0,
        cpp_start_age          = 65,
        oas_start_age          = 65,
        sp_cpp_start_age       = 65,
        sp_oas_start_age       = 65,
        province               = "ON",
        base_tax_year          = 2026,
        auto_tfsa_routing      = True,
        slow_go_age            = 75,
        slow_go_reduction_pct  = 18.75,
        no_go_age              = 85,
        no_go_reduction_pct    = 7.69,
        withdrawal_strategy    = WithdrawalStrategy.SIMPLE,
    )
    defaults.update(overrides)
    return ScenarioParams(**defaults)


def _row_at(rows: list[YearResult], age: int) -> YearResult:
    return next(r for r in rows if r.age_primary == age)


# ---------------------------------------------------------------------------
# Base Case — portfolio longevity
# ---------------------------------------------------------------------------

class TestBaseCaseLongevity:
    @pytest.fixture(scope="class")
    def result(self, primary, spouse):
        params  = _base_params()
        rows    = project_scenario(primary, params, spouse=spouse)
        summary = scenario_summary(params, rows)
        return rows, summary

    def test_no_depletion(self, result):
        """Base Case: portfolio should never hit zero to age 95."""
        _, summary = result
        assert summary["depletion_age"] is None, (
            f"Portfolio depleted at age {summary['depletion_age']} — expected no depletion"
        )

    def test_full_coverage(self, result):
        """Base Case: spending fully funded in all retirement years."""
        _, summary = result
        assert summary["avg_coverage_pct"] == pytest.approx(100.0, abs=0.1)
        assert summary["years_with_shortfall"] == 0

    def test_positive_estate_at_90(self, result):
        """Positive portfolio at age 90 — leaves an estate."""
        rows, _ = result
        row_90 = _row_at(rows, 90)
        assert row_90.portfolio_value > 0, "Portfolio depleted before age 90"
        # Calibrated range: 5% return, 3% inflation, spending phases applied
        assert 500_000 < row_90.portfolio_value < 1_000_000, (
            f"Estate at 90 out of expected range: ${row_90.portfolio_value:,.0f}"
        )

    def test_final_portfolio_at_95(self, result):
        """Calibrated: final portfolio at age 95 should be $400k–$750k."""
        _, summary = result
        assert 400_000 < summary["final_portfolio"] < 750_000, (
            f"Final portfolio ${summary['final_portfolio']:,.0f} out of calibrated range"
        )

    def test_no_shortfall_years(self, result):
        _, summary = result
        assert summary["years_with_shortfall"] == 0


# ---------------------------------------------------------------------------
# Base Case — Year 1 income composition (age 65)
# ---------------------------------------------------------------------------

class TestBaseCaseYear1Income:
    @pytest.fixture(scope="class")
    def row65(self, primary, spouse):
        params = _base_params()
        rows   = project_scenario(primary, params, spouse=spouse)
        return _row_at(rows, 65)

    def test_spending_target_inflation_adjusted(self, row65):
        """Year 1 spending target = $96,000 × 1.03^1 ≈ $98,880."""
        assert row65.spending_target == pytest.approx(98_880, abs=200), (
            f"Year 1 spending target: ${row65.spending_target:,.0f}"
        )

    def test_government_income_both_spouses(self, row65):
        """Household CPP + OAS ≈ $44,000–$45,000 (both spouses, inflated 1yr)."""
        gov = row65.cpp_income + row65.oas_income
        # 2026 rates: ($1,055 + $742) × 2 × 12 = $43,128 base → × 1.03 ≈ $44,422
        assert 43_000 < gov < 46_000, f"Household gov income year 1: ${gov:,.0f}"

    def test_portfolio_withdrawal_covers_gap(self, row65):
        """Portfolio withdrawal ≈ spending target minus government income."""
        gov = row65.cpp_income + row65.oas_income
        expected_gap = row65.spending_target - gov
        assert row65.portfolio_withdrawal == pytest.approx(expected_gap, abs=2_000), (
            f"Withdrawal ${row65.portfolio_withdrawal:,.0f} vs gap ${expected_gap:,.0f}"
        )

    def test_rrif_is_primary_withdrawal_source(self, row65):
        """SIMPLE strategy draws RRIF first — year 1 should be all RRIF."""
        # Before RRIF min kicks in at 72, draws go to RRIF first
        assert row65.withdrawal_from_rrif > 0, "Expected RRIF withdrawal in year 1"
        assert row65.withdrawal_from_tfsa == pytest.approx(0, abs=1), (
            "TFSA should not be drawn in year 1 (RRIF has capacity)"
        )

    def test_no_oas_clawback_year1(self, row65):
        """Income should be well below OAS clawback threshold (~$90k) in year 1."""
        assert row65.oas_clawback == pytest.approx(0, abs=1), (
            f"Unexpected OAS clawback in year 1: ${row65.oas_clawback:,.0f}"
        )

    def test_portfolio_withdrawal_in_expected_range(self, row65):
        """Year 1 portfolio withdrawal ≈ $52,000–$58,000."""
        assert 52_000 < row65.portfolio_withdrawal < 58_000, (
            f"Year 1 withdrawal: ${row65.portfolio_withdrawal:,.0f}"
        )


# ---------------------------------------------------------------------------
# Spending phases
# ---------------------------------------------------------------------------

class TestSpendingPhases:
    @pytest.fixture(scope="class")
    def rows(self, primary, spouse):
        params = _base_params()
        return project_scenario(primary, params, spouse=spouse)

    def test_slow_go_reduces_spending_at_75(self, rows):
        """Spending at age 75 should be ~81.25% of what age 74 trajectory would be."""
        row74 = _row_at(rows, 74)
        row75 = _row_at(rows, 75)
        # Expected: row75 target ≈ row74 target × 1.03 (one more year inflation) × 0.8125
        expected_75 = row74.spending_target * 1.03 * (1 - 18.75 / 100)
        assert row75.spending_target == pytest.approx(expected_75, abs=500), (
            f"Slow-go at 75: expected ~${expected_75:,.0f}, got ${row75.spending_target:,.0f}"
        )

    def test_no_go_reduces_spending_at_85(self, rows):
        """Spending at 85 applies additional no-go reduction on top of slow-go."""
        row84 = _row_at(rows, 84)
        row85 = _row_at(rows, 85)
        # At 84 slow-go is active; at 85 no-go adds further 7.69% reduction
        expected_85 = row84.spending_target * 1.03 * (1 - 7.69 / 100)
        assert row85.spending_target == pytest.approx(expected_85, abs=500), (
            f"No-go at 85: expected ~${expected_85:,.0f}, got ${row85.spending_target:,.0f}"
        )

    def test_slow_go_spending_less_than_without_phase(self, rows):
        """Slow-go phase results in lower spending than pre-phase trajectory."""
        row74 = _row_at(rows, 74)
        row75 = _row_at(rows, 75)
        # Without slow-go, age 75 would be ~row74 × 1.03
        unphased_75 = row74.spending_target * 1.03
        assert row75.spending_target < unphased_75, (
            "Slow-go should reduce age-75 spending below unphased trajectory"
        )

    def test_no_phase_before_75(self, rows):
        """Spending grows at inflation only (no phase reductions) before age 75."""
        row65 = _row_at(rows, 65)
        row66 = _row_at(rows, 66)
        # Each year spending grows exactly by inflation
        assert row66.spending_target == pytest.approx(row65.spending_target * 1.03, abs=10)


# ---------------------------------------------------------------------------
# Conservative scenario — mirrors video's ~94% figure
# ---------------------------------------------------------------------------

class TestConservativeScenario:
    @pytest.fixture(scope="class")
    def result(self, primary, spouse):
        params  = _base_params(name="Conservative", portfolio_return_pct=3.5)
        rows    = project_scenario(primary, params, spouse=spouse)
        summary = scenario_summary(params, rows)
        return rows, summary

    def test_coverage_below_100(self, result):
        """Conservative scenario should show <100% coverage (spending gap later)."""
        _, summary = result
        assert summary["avg_coverage_pct"] < 100.0, (
            "Conservative at 3.5% return should not be fully funded to 95"
        )

    def test_coverage_in_target_range(self, result):
        """Conservative coverage ~95-97% — close to video's '94% on track' spirit."""
        _, summary = result
        assert 90.0 <= summary["avg_coverage_pct"] <= 99.0, (
            f"Conservative coverage {summary['avg_coverage_pct']:.1f}% out of expected 90–99% range"
        )

    def test_positive_estate_at_90(self, result):
        """Conservative: should still have positive portfolio at age 90."""
        rows, _ = result
        row_90 = _row_at(rows, 90)
        assert row_90.portfolio_value > 0, (
            f"Conservative portfolio depleted before age 90: ${row_90.portfolio_value:,.0f}"
        )

    def test_depletion_near_or_at_horizon(self, result):
        """Conservative: depletes near the 95-year horizon, not in early retirement."""
        _, summary = result
        if summary["depletion_age"] is not None:
            assert summary["depletion_age"] >= 88, (
                f"Conservative depletes too early at age {summary['depletion_age']}"
            )


# ---------------------------------------------------------------------------
# Household inputs sanity checks
# ---------------------------------------------------------------------------

class TestHouseholdInputs:
    def test_total_portfolio_is_one_million(self, primary, spouse):
        """Combined household starting portfolio = $1,000,000."""
        total = (
            primary.rrsp_rrif_balance + primary.tfsa_balance + primary.non_registered_balance
            + spouse.rrsp_rrif_balance + spouse.tfsa_balance + spouse.non_registered_balance
        )
        assert total == 1_000_000

    def test_pension_income_at_65(self):
        """Household CPP + OAS base (before inflation) ≈ $43,128/yr."""
        cpp_each = 1_055 * 12   # $12,660/yr
        oas_each = 742 * 12     # $8,904/yr
        household_gov = (cpp_each + oas_each) * 2
        assert household_gov == pytest.approx(43_128, abs=10)

    def test_pension_covers_45pct_of_spending(self):
        """Government income covers ~45% of $96k spending — rest from portfolio."""
        gov = (1_055 + 742) * 2 * 12
        coverage = gov / 96_000
        assert 0.40 < coverage < 0.50


# ---------------------------------------------------------------------------
# Auto-TFSA routing (excess RRIF flows to TFSA not non-reg)
# ---------------------------------------------------------------------------

class TestAutoTfsaRouting:
    def test_tfsa_balance_grows_when_routing_enabled(self, primary, spouse):
        """When auto_tfsa_routing=True, TFSA balance should grow over early years
        as RRIF minimum excess is sheltered."""
        params_on  = _base_params(auto_tfsa_routing=True)
        params_off = _base_params(auto_tfsa_routing=False)
        rows_on    = project_scenario(primary, params_on, spouse=spouse)
        rows_off   = project_scenario(primary, params_off, spouse=spouse)

        # After RRIF minimums kick in at 72, TFSA should be higher with routing
        row_on_80  = _row_at(rows_on, 80)
        row_off_80 = _row_at(rows_off, 80)
        assert row_on_80.tfsa_balance >= row_off_80.tfsa_balance, (
            "Auto-TFSA routing should result in equal or higher TFSA balance at 80"
        )
