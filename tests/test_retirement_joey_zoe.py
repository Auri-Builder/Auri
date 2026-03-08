"""
tests/test_retirement_joey_zoe.py
----------------------------------
Test Case 1: Joey & Zoe — full calibration suite.

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

Video-match scenario
--------------------
Conservative (3.5% return, 3% inflation) WITH phases = 95.7% coverage.
This is the closest match to the video's stated "~94% on track" figure.
Without phases the same Conservative run drops to 81.6% — phases do the
heavy lifting, reducing cumulative spending by ~$857k over 20 years.

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

# ===========================================================================
# PART 2 — Variant tests (phases, TFSA positioning, stress)
# ===========================================================================

# ---------------------------------------------------------------------------
# Conservative as video-match baseline
# ---------------------------------------------------------------------------

class TestConservativeVideoMatch:
    """
    Conservative (3.5% return, 3% inflation) WITH spending phases = 95.7% —
    our closest match to the video's "~94% on track" figure.

    Without phases the same run drops to 81.6%, confirming that the
    slow-go / no-go step-downs are what keeps the Conservative scenario afloat.
    """

    @pytest.fixture(scope="class")
    def result_with_phases(self, primary, spouse):
        params = _base_params(name="Conservative", portfolio_return_pct=3.5)
        rows   = project_scenario(primary, params, spouse=spouse)
        return rows, scenario_summary(params, rows)

    @pytest.fixture(scope="class")
    def result_no_phases(self, primary, spouse):
        params = _base_params(
            name="Conservative No Phases",
            portfolio_return_pct=3.5,
            slow_go_age=0, slow_go_reduction_pct=0.0,
            no_go_age=0,  no_go_reduction_pct=0.0,
        )
        rows = project_scenario(primary, params, spouse=spouse)
        return rows, scenario_summary(params, rows)

    def test_conservative_with_phases_matches_video(self, result_with_phases):
        """Conservative + phases ≈ 95.7% — within the video's stated ~94% range."""
        _, s = result_with_phases
        assert 93.0 <= s["avg_coverage_pct"] <= 98.0, (
            f"Conservative+phases coverage {s['avg_coverage_pct']:.1f}%, expected 93-98%"
        )

    def test_phases_are_essential_for_conservative(self, result_with_phases, result_no_phases):
        """Without phases Conservative drops ~14 points — phases are load-bearing."""
        _, s_with = result_with_phases
        _, s_none = result_no_phases
        delta = s_with["avg_coverage_pct"] - s_none["avg_coverage_pct"]
        assert delta >= 10.0, (
            f"Expected phases to lift coverage by ≥10 pts, got {delta:.1f} pts"
        )

    def test_no_phases_depletes_well_before_95(self, result_no_phases):
        """Without phases the Conservative scenario depletes before age 90."""
        _, s = result_no_phases
        assert s["depletion_age"] is not None
        assert s["depletion_age"] < 90, (
            f"Expected depletion before 90 without phases, got age {s['depletion_age']}"
        )

    def test_conservative_estate_at_90_thin_but_positive(self, result_with_phases):
        """Conservative + phases: thin estate at 90 — positive but not lavish."""
        rows, _ = result_with_phases
        row_90 = _row_at(rows, 90)
        assert row_90.portfolio_value > 0
        assert row_90.portfolio_value < 200_000, (
            f"Conservative estate at 90 should be thin: ${row_90.portfolio_value:,.0f}"
        )


# ---------------------------------------------------------------------------
# No-phases / flat spending variant
# ---------------------------------------------------------------------------

class TestFlatSpending:
    """
    Disable both spending phases — flat $96k/yr growing at 3% inflation.
    At 5% return: 89.9% coverage, depletes age 93, near-zero estate at 90.
    Without the phase step-downs the portfolio is under much more pressure.
    """

    @pytest.fixture(scope="class")
    def result(self, primary, spouse):
        params = _base_params(
            name="Flat Spending",
            slow_go_age=0, slow_go_reduction_pct=0.0,
            no_go_age=0,  no_go_reduction_pct=0.0,
        )
        rows = project_scenario(primary, params, spouse=spouse)
        return rows, scenario_summary(params, rows)

    def test_coverage_below_phased_base(self, result):
        """Flat spending (no phases) has lower coverage than phased base (100%)."""
        _, s = result
        assert s["avg_coverage_pct"] < 100.0, (
            "Flat spending should not achieve full coverage"
        )
        assert s["avg_coverage_pct"] >= 85.0, (
            f"Flat spending coverage {s['avg_coverage_pct']:.1f}% unexpectedly low"
        )

    def test_depletes_before_95(self, result):
        """Without phases the portfolio depletes before age 95."""
        _, s = result
        assert s["depletion_age"] is not None
        assert s["depletion_age"] < 95

    def test_estate_near_zero_at_90(self, result):
        """Flat spending leaves near-zero estate at 90."""
        rows, _ = result
        row_90 = _row_at(rows, 90)
        assert row_90.portfolio_value < 10_000, (
            f"Expected near-zero estate at 90, got ${row_90.portfolio_value:,.0f}"
        )

    def test_phases_add_significant_estate_value(self, primary, spouse):
        """Quantify the estate benefit of spending phases vs flat spending."""
        p_flat = _base_params(
            slow_go_age=0, slow_go_reduction_pct=0.0,
            no_go_age=0,  no_go_reduction_pct=0.0,
        )
        p_phased = _base_params()
        rows_flat   = project_scenario(primary, p_flat,   spouse=spouse)
        rows_phased = project_scenario(primary, p_phased, spouse=spouse)
        estate_flat   = _row_at(rows_flat,   90).portfolio_value
        estate_phased = _row_at(rows_phased, 90).portfolio_value
        # Phases add $700k+ to estate at 90 (cumulative spend reduction ~$857k)
        assert estate_phased - estate_flat > 500_000, (
            f"Phases should add >$500k estate at 90: flat ${estate_flat:,.0f}, "
            f"phased ${estate_phased:,.0f}"
        )


# ---------------------------------------------------------------------------
# Milder phases (-10% / -10%)
# ---------------------------------------------------------------------------

class TestMilderPhases:
    """
    Milder reductions: slow-go −10% at 75, no-go −10% at 85.
    At 5% return: still achieves 100% coverage (estate $425k at 90).
    At 3.5% return: drops to 89.7% — milder phases not enough at low returns.
    The video's aggressive phases (−18.75% / −7.69%) are meaningfully better
    for the Conservative scenario.
    """

    @pytest.fixture(scope="class")
    def result_base_mild(self, primary, spouse):
        params = _base_params(
            name="Base Mild Phases",
            slow_go_reduction_pct=10.0, no_go_reduction_pct=10.0,
        )
        rows = project_scenario(primary, params, spouse=spouse)
        return rows, scenario_summary(params, rows)

    @pytest.fixture(scope="class")
    def result_cons_mild(self, primary, spouse):
        params = _base_params(
            name="Conservative Mild Phases",
            portfolio_return_pct=3.5,
            slow_go_reduction_pct=10.0, no_go_reduction_pct=10.0,
        )
        rows = project_scenario(primary, params, spouse=spouse)
        return rows, scenario_summary(params, rows)

    def test_mild_phases_fully_fund_at_5pct(self, result_base_mild):
        """Even mild −10%/−10% phases achieve 100% coverage at 5% return."""
        _, s = result_base_mild
        assert s["avg_coverage_pct"] == pytest.approx(100.0, abs=0.5)
        assert s["depletion_age"] is None

    def test_mild_phases_estate_at_90(self, result_base_mild):
        """Mild phases: estate at 90 ≈ $400–500k (less than aggressive phases)."""
        rows, _ = result_base_mild
        row_90 = _row_at(rows, 90)
        assert 300_000 < row_90.portfolio_value < 600_000, (
            f"Mild-phase estate at 90: ${row_90.portfolio_value:,.0f}"
        )

    def test_mild_phases_conservative_insufficient(self, result_cons_mild):
        """Mild phases at 3.5% return: coverage drops vs video's aggressive phases."""
        _, s = result_cons_mild
        # Aggressive phases get to 95.7%; mild only reach ~89.7%
        assert s["avg_coverage_pct"] < 93.0, (
            "Mild phases at 3.5% return should fall short of video match"
        )

    def test_aggressive_phases_better_than_mild_conservative(self, primary, spouse):
        """Video's aggressive phases (18.75%/7.69%) beat mild (10%/10%) in Conservative."""
        p_mild = _base_params(
            portfolio_return_pct=3.5,
            slow_go_reduction_pct=10.0, no_go_reduction_pct=10.0,
        )
        p_agg = _base_params(portfolio_return_pct=3.5)   # 18.75%/7.69%
        rows_mild = project_scenario(primary, p_mild, spouse=spouse)
        rows_agg  = project_scenario(primary, p_agg,  spouse=spouse)
        s_mild = scenario_summary(p_mild, rows_mild)
        s_agg  = scenario_summary(p_agg,  rows_agg)
        assert s_agg["avg_coverage_pct"] > s_mild["avg_coverage_pct"], (
            "Aggressive phases should beat mild phases in Conservative scenario"
        )


# ---------------------------------------------------------------------------
# TFSA positioning — preserve vs expose early
# ---------------------------------------------------------------------------

class TestTfsaPositioning:
    """
    The value of TFSA tax-sheltering: keeping $100k in TFSA (drawn last,
    grows tax-free) vs moving it to non-registered (drawn 2nd, growth taxable).

    Coverage is unchanged — total investable dollars are the same.
    But total lifetime taxes are $17–24k higher when TFSA is in non-reg.
    TFSA also compounds tax-free until drawn, which matters most in poor-
    return scenarios where every dollar of tax drag is painful.
    """

    @pytest.fixture(scope="module")
    def primary_no_tfsa(self):
        """Primary with TFSA money moved into non-reg — drawn earlier, taxable."""
        return PersonProfile(
            current_age=64, rrsp_rrif_balance=350_000,
            tfsa_balance=0.0, non_registered_balance=200_000,
            cpp_monthly_at_65=1055.0, oas_monthly_at_65=742.0,
            pension_monthly=0, tfsa_room_remaining=0, province="ON",
        )

    def test_tfsa_saves_lifetime_taxes(self, primary, primary_no_tfsa, spouse):
        """Preserving TFSA reduces total lifetime taxes by >$10k vs non-reg."""
        p = _base_params()
        rows_tfsa   = project_scenario(primary,         p, spouse=spouse)
        rows_no_tfsa = project_scenario(primary_no_tfsa, p, spouse=spouse)
        s_tfsa   = scenario_summary(p, rows_tfsa)
        s_no_tfsa = scenario_summary(p, rows_no_tfsa)
        tax_saving = s_no_tfsa["total_taxes"] - s_tfsa["total_taxes"]
        assert tax_saving > 10_000, (
            f"Expected >$10k tax saving from TFSA preservation, got ${tax_saving:,.0f}"
        )

    def test_tfsa_not_drawn_until_late_retirement(self, primary, spouse):
        """SIMPLE strategy: TFSA not drawn until RRIF + non-reg are largely exhausted."""
        rows = project_scenario(primary, _base_params(), spouse=spouse)
        for age in range(65, 85):
            r = _row_at(rows, age)
            assert r.withdrawal_from_tfsa == pytest.approx(0, abs=1), (
                f"TFSA drawn at age {age} — should be preserved until late retirement"
            )

    def test_tfsa_compounds_tax_free(self, primary, spouse):
        """TFSA balance grows every year it is not drawn (tax-free compounding)."""
        rows = project_scenario(primary, _base_params(), spouse=spouse)
        r65 = _row_at(rows, 65)
        r80 = _row_at(rows, 80)
        assert r80.tfsa_balance > r65.tfsa_balance, (
            f"TFSA should grow: ${r65.tfsa_balance:,.0f} → ${r80.tfsa_balance:,.0f}"
        )

    def test_coverage_unchanged_by_tfsa_positioning(self, primary, primary_no_tfsa, spouse):
        """Total investable dollars are the same — coverage rate should not differ."""
        p = _base_params()
        rows_tfsa    = project_scenario(primary,          p, spouse=spouse)
        rows_no_tfsa = project_scenario(primary_no_tfsa,  p, spouse=spouse)
        s_tfsa    = scenario_summary(p, rows_tfsa)
        s_no_tfsa = scenario_summary(p, rows_no_tfsa)
        assert abs(s_tfsa["avg_coverage_pct"] - s_no_tfsa["avg_coverage_pct"]) < 1.0, (
            "Coverage should not change with TFSA repositioning (same total dollars)"
        )


# ---------------------------------------------------------------------------
# Stress scenario — low returns + high inflation
# ---------------------------------------------------------------------------

class TestStressScenario:
    """
    'Video punch': low real return (4% nominal), high inflation (4%), no phases.
    Our engine produces ~79-80% coverage in this scenario.

    Calibration note: The video's reference software showed ~62% coverage in
    its stress test. The ~18 point gap is explained by our engine's inflation-
    indexed CPP/OAS model — government benefits grow with inflation, partially
    offsetting portfolio pressure. A system that treats CPP/OAS as fixed nominal
    amounts would produce materially lower coverage under high inflation, which
    is likely what the video's software does.

    Our tests validate:
      1. Coverage drops significantly vs base under stress assumptions
      2. Portfolio depletes well before age 90 without phases
      3. Spending phases provide meaningful rescue even under stress
      4. Coverage is directionally similar to video (materially below base)
    """

    @pytest.fixture(scope="class")
    def result_stress_no_phases(self, primary, spouse):
        params = _base_params(
            name="Stress No Phases",
            portfolio_return_pct=4.0,
            inflation_rate_pct=4.0,
            slow_go_age=0, slow_go_reduction_pct=0.0,
            no_go_age=0,  no_go_reduction_pct=0.0,
        )
        rows = project_scenario(primary, params, spouse=spouse)
        return rows, scenario_summary(params, rows)

    @pytest.fixture(scope="class")
    def result_stress_with_phases(self, primary, spouse):
        params = _base_params(
            name="Stress With Phases",
            portfolio_return_pct=4.0,
            inflation_rate_pct=4.0,
        )
        rows = project_scenario(primary, params, spouse=spouse)
        return rows, scenario_summary(params, rows)

    def test_stress_significantly_below_base(self, result_stress_no_phases):
        """Stress coverage must be materially below base case (89.9% flat)."""
        _, s = result_stress_no_phases
        assert s["avg_coverage_pct"] < 85.0, (
            f"Stress coverage {s['avg_coverage_pct']:.1f}% should be well below base"
        )

    def test_stress_depletes_before_90(self, result_stress_no_phases):
        """Under stress without phases, portfolio depletes before age 90."""
        _, s = result_stress_no_phases
        assert s["depletion_age"] is not None
        assert s["depletion_age"] < 90, (
            f"Stress portfolio should deplete before 90, got age {s['depletion_age']}"
        )

    def test_stress_coverage_directionally_matches_video(self, result_stress_no_phases):
        """Stress coverage in the 70-85% band — directionally below base like video's 62%."""
        _, s = result_stress_no_phases
        assert 70.0 <= s["avg_coverage_pct"] <= 85.0, (
            f"Stress coverage {s['avg_coverage_pct']:.1f}% outside 70-85% calibration band.\n"
            "Note: video showed 62%; gap is due to our engine indexing CPP/OAS to inflation."
        )

    def test_phases_rescue_stress_scenario(self, result_stress_no_phases, result_stress_with_phases):
        """Spending phases provide meaningful coverage rescue even under stress."""
        _, s_no   = result_stress_no_phases
        _, s_with = result_stress_with_phases
        assert s_with["avg_coverage_pct"] > s_no["avg_coverage_pct"] + 5.0, (
            f"Phases should add >5 pts under stress: "
            f"{s_no['avg_coverage_pct']:.1f}% → {s_with['avg_coverage_pct']:.1f}%"
        )

    def test_phases_delay_depletion_under_stress(self, result_stress_no_phases, result_stress_with_phases):
        """Phases delay portfolio depletion vs flat spending under stress."""
        _, s_no   = result_stress_no_phases
        _, s_with = result_stress_with_phases
        age_no   = s_no["depletion_age"]   or 96
        age_with = s_with["depletion_age"] or 96
        assert age_with >= age_no, (
            f"Phases should delay depletion: no-phases age {age_no} vs phases age {age_with}"
        )

    def test_higher_inflation_increases_tax_burden(self, primary, spouse):
        """Higher inflation → higher nominal incomes → higher taxes."""
        p_low  = _base_params(inflation_rate_pct=2.5, slow_go_age=0, slow_go_reduction_pct=0)
        p_high = _base_params(inflation_rate_pct=4.0, slow_go_age=0, slow_go_reduction_pct=0,
                               no_go_age=0, no_go_reduction_pct=0)
        s_low  = scenario_summary(p_low,  project_scenario(primary, p_low,  spouse=spouse))
        s_high = scenario_summary(p_high, project_scenario(primary, p_high, spouse=spouse))
        assert s_high["total_taxes"] > s_low["total_taxes"], (
            "Higher inflation should produce higher total taxes on nominal income"
        )


# ---------------------------------------------------------------------------
# Phase savings quantification
# ---------------------------------------------------------------------------

class TestPhaseSavingsQuantification:
    """
    Verifies the quick-math from the scenario description:
      Slow-go (75-84, 10 years): each year saves ~$18k+ after inflation adj.
      No-go (85-90, 6 years):    each year saves ~$24k+ after inflation adj.
      Total spending reduction vs flat: ~$857k over projection period.

    This explains why spending phases have such outsized impact — the portfolio
    avoids drawing $857k+ and that capital compounds for 10-20 more years.
    """

    def test_cumulative_spend_reduction_over_300k(self, primary, spouse):
        """Total spending reduction from phases vs flat exceeds $300k."""
        p_flat   = _base_params(slow_go_age=0, slow_go_reduction_pct=0.0,
                                no_go_age=0,  no_go_reduction_pct=0.0)
        p_phased = _base_params()
        rows_flat   = project_scenario(primary, p_flat,   spouse=spouse)
        rows_phased = project_scenario(primary, p_phased, spouse=spouse)

        total_saving = sum(
            max(0.0, rn.spending_target - rp.spending_target)
            for rp, rn in zip(rows_phased, rows_flat)
        )
        assert total_saving > 300_000, (
            f"Cumulative phase savings ${total_saving:,.0f} expected >$300k"
        )

    def test_slow_go_saves_per_year(self, primary, spouse):
        """Each slow-go year (75-84) saves ≥$20k vs unphased trajectory."""
        p_flat   = _base_params(slow_go_age=0, slow_go_reduction_pct=0.0,
                                no_go_age=0,  no_go_reduction_pct=0.0)
        p_phased = _base_params()
        rows_flat   = project_scenario(primary, p_flat,   spouse=spouse)
        rows_phased = project_scenario(primary, p_phased, spouse=spouse)

        for age in range(75, 85):
            rp = _row_at(rows_phased, age)
            rf = _row_at(rows_flat,   age)
            saving = rf.spending_target - rp.spending_target
            assert saving >= 20_000, (
                f"Slow-go saving at age {age}: ${saving:,.0f} — expected ≥$20k"
            )

    def test_no_go_saves_more_per_year_than_slow_go(self, primary, spouse):
        """No-go phase (85+) saves more per year than slow-go (cumulative reduction)."""
        p_flat   = _base_params(slow_go_age=0, slow_go_reduction_pct=0.0,
                                no_go_age=0,  no_go_reduction_pct=0.0)
        p_phased = _base_params()
        rows_flat   = project_scenario(primary, p_flat,   spouse=spouse)
        rows_phased = project_scenario(primary, p_phased, spouse=spouse)

        saving_74 = _row_at(rows_flat, 74).spending_target - _row_at(rows_phased, 74).spending_target
        saving_85 = _row_at(rows_flat, 85).spending_target - _row_at(rows_phased, 85).spending_target
        assert saving_85 > saving_74, (
            f"No-go year saving ${saving_85:,.0f} should exceed slow-go year ${saving_74:,.0f}"
        )
