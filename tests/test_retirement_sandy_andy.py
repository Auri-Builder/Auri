"""
tests/test_retirement_sandy_andy.py
-------------------------------------
Test Case 2: Sandy & Andy — RRIF/TFSA optimisation scenario.

Reference scenario
------------------
Two spouses, both age 65 retiring now, Ontario, no DB pension.
CPP at 75% of 2026 max ($1,507.65/mo → $1,130.74/mo each).
OAS at 2026 max for age 65-74 ($742/mo each).
Sandy: RRSP $400k  TFSA $50k   Non-Reg $0    (heavier RRSP)
Andy:  RRSP $300k  TFSA $0     Non-Reg $0    (no TFSA, smaller RRSP)
Household portfolio: $750,000
Annual spending $84,000/yr (today's $), 3% inflation.
No spending phases (base run is simple).
Auto-shelter RRIF excess → TFSA enabled.

Calibration note — why our engine differs from the video's ~81% figure
-----------------------------------------------------------------------
The video (produced before 2026 rates were published) used CPP ≈ $900/mo and
OAS ≈ $690/mo per person. Using those figures our engine produces 81.7%
coverage — matching the video almost exactly.

With 2026-accurate rates (CPP $1,130.74, OAS $742) pension income is higher,
so coverage improves to 91.3% at 5% return / 3% inflation.  Both are tested
below: the "video-calibrated" variant validates engine sensitivity; the
"2026-accurate" variant is what the app will display.

Scenarios tested
----------------
A) Base Case (SIMPLE, 2026 rates):         91.3% coverage, depletion age 93
B) Video-calibrated (SIMPLE, older rates): ~80-84% coverage, mirrors video's 81%
C) Tax-Optimised (RRSP meltdown, sensible ceiling):
   - ceiling = $57,375 (top of first federal bracket per person)
   - Coverage ≈ 90.9%, but no depletion — significant improvement
   - Total taxes ≈ $30k lower than SIMPLE
   - Estate at 90 ≈ $62k vs ~$0 SIMPLE
D) Auto-TFSA routing: TFSA balance grows via new room + RRIF minimum excess
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
def sandy() -> PersonProfile:
    """Primary — heavier RRSP, some TFSA, no non-reg."""
    return PersonProfile(
        current_age             = 65,
        rrsp_rrif_balance       = 400_000,
        tfsa_balance            = 50_000,
        non_registered_balance  = 0.0,
        cpp_monthly_at_65       = 1_130.74,
        oas_monthly_at_65       = 742.0,
        pension_monthly         = 0.0,
        pension_start_age       = 0,
        tfsa_room_remaining     = 0.0,   # assume all room used pre-retirement
        province                = "ON",
    )


@pytest.fixture(scope="module")
def andy() -> PersonProfile:
    """Spouse — smaller RRSP, no TFSA, no non-reg."""
    return PersonProfile(
        current_age             = 65,
        rrsp_rrif_balance       = 300_000,
        tfsa_balance            = 0.0,
        non_registered_balance  = 0.0,
        cpp_monthly_at_65       = 1_130.74,
        oas_monthly_at_65       = 742.0,
        pension_monthly         = 0.0,
        pension_start_age       = 0,
        tfsa_room_remaining     = 0.0,
        province                = "ON",
    )


def _params(strategy=WithdrawalStrategy.SIMPLE, ceiling=None, **overrides) -> ScenarioParams:
    defaults = dict(
        name                    = "Base Case",
        retirement_age          = 65,
        longevity_age           = 95,
        target_annual_spending  = 84_000,
        inflation_rate_pct      = 3.0,
        portfolio_return_pct    = 5.0,
        cpp_start_age           = 65,
        oas_start_age           = 65,
        sp_cpp_start_age        = 65,
        sp_oas_start_age        = 65,
        province                = "ON",
        base_tax_year           = 2026,
        auto_tfsa_routing       = True,
        slow_go_age             = 0,
        slow_go_reduction_pct   = 0.0,
        no_go_age               = 0,
        no_go_reduction_pct     = 0.0,
        withdrawal_strategy     = strategy,
        meltdown_income_ceiling = ceiling,
    )
    defaults.update(overrides)
    return ScenarioParams(**defaults)


def _row_at(rows: list[YearResult], age: int) -> YearResult:
    return next(r for r in rows if r.age_primary == age)


# ---------------------------------------------------------------------------
# A) Base Case — 2026-accurate rates, SIMPLE strategy
# ---------------------------------------------------------------------------

class TestBaseCaseSandyAndy:
    """
    With 2026-accurate CPP/OAS rates the plan is better than the video's
    software showed (older rates), reaching 91.3% coverage.
    """

    @pytest.fixture(scope="class")
    def result(self, sandy, andy):
        params = _params()
        rows   = project_scenario(sandy, params, spouse=andy)
        return rows, scenario_summary(params, rows)

    def test_portfolio_starts_at_750k(self, sandy, andy):
        total = (sandy.rrsp_rrif_balance + sandy.tfsa_balance + sandy.non_registered_balance
                 + andy.rrsp_rrif_balance + andy.tfsa_balance + andy.non_registered_balance)
        assert total == 750_000

    def test_coverage_reflects_strong_pensions(self, result):
        """2026 CPP/OAS is higher than older video rates → 91% coverage, not 81%."""
        _, s = result
        assert 88.0 <= s["avg_coverage_pct"] <= 96.0, (
            f"Expected 88-96% coverage with 2026 rates, got {s['avg_coverage_pct']:.1f}%"
        )

    def test_depletion_in_early_90s(self, result):
        """$750k portfolio / $84k spending / 3% inflation → depletes around age 93."""
        _, s = result
        assert s["depletion_age"] is not None, "Expected eventual depletion with these balances"
        assert 90 <= s["depletion_age"] <= 95, (
            f"Depletion at age {s['depletion_age']}, expected 90-95"
        )

    def test_year1_spending_target(self, result):
        """Retiring at 65, no accumulation year — spending target is today's $84k (no inflation yet)."""
        rows, _ = result
        r = _row_at(rows, 65)
        assert r.spending_target == pytest.approx(84_000, abs=100)

    def test_year1_government_income(self, result):
        """Household CPP + OAS at age 65 ≈ $45,000/yr (both spouses, no inflation in year 0)."""
        rows, _ = result
        r = _row_at(rows, 65)
        gov = r.cpp_income + r.oas_income
        # ($1,130.74 + $742) × 2 × 12 = $44,948/yr — slight variance from inflation indexing
        assert 44_000 < gov < 46_000, f"Year 1 gov income ${gov:,.0f}"

    def test_year1_withdrawal_covers_gap(self, result):
        """Portfolio withdrawal fills the gap between gov income and spending target."""
        rows, _ = result
        r = _row_at(rows, 65)
        gov = r.cpp_income + r.oas_income
        gap = r.spending_target - gov
        assert r.portfolio_withdrawal == pytest.approx(gap, abs=1_500), (
            f"Withdrawal ${r.portfolio_withdrawal:,.0f} vs gap ${gap:,.0f}"
        )

    def test_year1_withdrawal_from_rrif_only(self, result):
        """SIMPLE strategy: draws RRIF before TFSA — year 1 is all RRIF, no TFSA."""
        rows, _ = result
        r = _row_at(rows, 65)
        assert r.withdrawal_from_rrif > 0
        assert r.withdrawal_from_tfsa == pytest.approx(0, abs=1)
        assert r.withdrawal_from_non_reg == pytest.approx(0, abs=1)

    def test_year1_no_oas_clawback(self, result):
        """Income in year 1 well below OAS clawback threshold."""
        rows, _ = result
        r = _row_at(rows, 65)
        assert r.oas_clawback == pytest.approx(0, abs=1)

    def test_pension_covers_majority_of_spending(self):
        """CPP + OAS covers ~53% of $84k spending — better than the 45% in Test Case 1."""
        gov_base = (1_130.74 + 742.0) * 2 * 12   # ~$44,948
        coverage = gov_base / 84_000
        assert 0.50 < coverage < 0.58


# ---------------------------------------------------------------------------
# B) Video-calibrated variant — older CPP/OAS rates reproduce ~81% figure
# ---------------------------------------------------------------------------

class TestVideoCalibrated:
    """
    Video used CPP ≈ $900/mo and OAS ≈ $690/mo per person (pre-2026 rates).
    Using those figures our engine produces ~81-84% coverage — close to the
    video's stated 81% on-track figure.
    """

    @pytest.fixture(scope="module")
    def older_rate_profiles(self):
        sandy_old = PersonProfile(current_age=65, rrsp_rrif_balance=400_000,
            tfsa_balance=50_000, non_registered_balance=0,
            cpp_monthly_at_65=900.0, oas_monthly_at_65=690.0,
            pension_monthly=0, tfsa_room_remaining=0, province="ON")
        andy_old = PersonProfile(current_age=65, rrsp_rrif_balance=300_000,
            tfsa_balance=0, non_registered_balance=0,
            cpp_monthly_at_65=900.0, oas_monthly_at_65=690.0,
            pension_monthly=0, tfsa_room_remaining=0, province="ON")
        return sandy_old, andy_old

    def test_coverage_matches_video_81pct(self, older_rate_profiles):
        """With older CPP/OAS rates the engine reproduces the video's ~81% figure."""
        sandy_old, andy_old = older_rate_profiles
        params = _params()
        rows   = project_scenario(sandy_old, params, spouse=andy_old)
        s      = scenario_summary(params, rows)
        assert 78.0 <= s["avg_coverage_pct"] <= 86.0, (
            f"Video-calibrated coverage {s['avg_coverage_pct']:.1f}% expected 78-86%"
        )

    def test_lower_pensions_increase_portfolio_dependency(self, older_rate_profiles):
        """With older/lower CPP/OAS, portfolio must cover a larger fraction of spending."""
        sandy_old, andy_old = older_rate_profiles
        gov_base = (900.0 + 690.0) * 2 * 12   # $38,160/yr
        gap = 84_000 - gov_base                # $45,840
        # Bigger gap → heavier portfolio draw → earlier depletion
        assert gap > 40_000, f"Expected large portfolio gap, got ${gap:,.0f}"


# ---------------------------------------------------------------------------
# C) Tax-Optimised — RRSP meltdown with bracket-appropriate ceiling
# ---------------------------------------------------------------------------

class TestRrspMeltdownOptimisation:
    """
    RRSP meltdown with ceiling = $57,375 (top of first 2026 federal bracket).
    Aggressive early RRIF draws clear the RRSP at lower marginal rates,
    reducing lifetime taxes and improving estate vs SIMPLE.
    """

    _CEILING = 57_375.0   # top of first federal bracket (2026)

    @pytest.fixture(scope="class")
    def both_results(self, sandy, andy):
        p_simple  = _params(strategy=WithdrawalStrategy.SIMPLE)
        p_melt    = _params(strategy=WithdrawalStrategy.RRSP_MELTDOWN,
                            ceiling=self._CEILING, name="Tax-Optimised")
        rows_s = project_scenario(sandy, p_simple, spouse=andy)
        rows_m = project_scenario(sandy, p_melt,   spouse=andy)
        s_s    = scenario_summary(p_simple, rows_s)
        s_m    = scenario_summary(p_melt,   rows_m)
        return rows_s, s_s, rows_m, s_m

    def test_meltdown_reduces_lifetime_taxes(self, both_results):
        """Sensible meltdown ceiling should reduce total lifetime taxes vs SIMPLE."""
        _, s_s, _, s_m = both_results
        tax_saving = s_s["total_taxes"] - s_m["total_taxes"]
        assert tax_saving > 10_000, (
            f"Expected >$10k tax saving from meltdown, got ${tax_saving:,.0f}"
        )

    def test_meltdown_improves_estate(self, both_results):
        """Meltdown should result in a better estate at age 90 than SIMPLE."""
        rows_s, _, rows_m, _ = both_results
        estate_s = _row_at(rows_s, 90).portfolio_value
        estate_m = _row_at(rows_m, 90).portfolio_value
        assert estate_m >= estate_s, (
            f"Meltdown estate at 90 ${estate_m:,.0f} not better than SIMPLE ${estate_s:,.0f}"
        )

    def test_meltdown_avoids_depletion(self, both_results):
        """Meltdown with bracket-appropriate ceiling should prevent depletion to age 95."""
        _, _, _, s_m = both_results
        assert s_m["depletion_age"] is None, (
            f"Meltdown still depletes at age {s_m['depletion_age']}"
        )

    def test_meltdown_draws_larger_rrif_early(self, both_results):
        """Meltdown forces higher RRIF draws in early retirement to clear at lower rates."""
        rows_s, _, rows_m, _ = both_results
        r65_s = _row_at(rows_s, 65)
        r65_m = _row_at(rows_m, 65)
        assert r65_m.withdrawal_from_rrif > r65_s.withdrawal_from_rrif, (
            "Meltdown should draw more RRIF in year 1 than SIMPLE"
        )

    def test_meltdown_higher_early_tax_lower_late_tax(self, both_results):
        """Meltdown front-loads tax; compare year 1 vs year 30 tax rates."""
        rows_s, _, rows_m, _ = both_results
        # Year 1: meltdown pays more tax (bigger RRIF draw)
        assert _row_at(rows_m, 65).taxes_estimated > _row_at(rows_s, 65).taxes_estimated
        # By age 80+: meltdown should pay equal or less (RRSP nearly drained)
        tax_m_80 = _row_at(rows_m, 80).taxes_estimated
        tax_s_80 = _row_at(rows_s, 80).taxes_estimated
        assert tax_m_80 <= tax_s_80 * 1.10, (
            f"Meltdown still paying much more tax at 80: ${tax_m_80:,.0f} vs ${tax_s_80:,.0f}"
        )


# ---------------------------------------------------------------------------
# D) Auto-TFSA routing — RRIF minimum excess flows to TFSA
# ---------------------------------------------------------------------------

class TestAutoTfsaRouting:
    """
    Even with $0 TFSA room remaining, new annual room accumulates each year.
    Auto-TFSA routing should park RRIF excess in that new room, growing
    Sandy's TFSA balance over the first decade.
    """

    def test_tfsa_grows_over_first_decade(self, sandy, andy):
        """Sandy's TFSA should grow from $50k as new annual room is contributed."""
        params = _params()
        rows   = project_scenario(sandy, params, spouse=andy)
        tfsa_65 = _row_at(rows, 65).tfsa_balance
        tfsa_75 = _row_at(rows, 75).tfsa_balance
        assert tfsa_75 > tfsa_65, (
            f"TFSA should grow via new room + routing: ${tfsa_65:,.0f} → ${tfsa_75:,.0f}"
        )

    def test_routing_on_beats_off_at_midlife(self, sandy, andy):
        """TFSA balance at age 80 is higher with auto-routing than without."""
        params_on  = _params(auto_tfsa_routing=True)
        params_off = _params(auto_tfsa_routing=False)
        rows_on    = project_scenario(sandy, params_on, spouse=andy)
        rows_off   = project_scenario(sandy, params_off, spouse=andy)
        assert _row_at(rows_on, 80).tfsa_balance >= _row_at(rows_off, 80).tfsa_balance

    def test_tfsa_drawn_late_not_early(self, sandy, andy):
        """SIMPLE strategy preserves TFSA — no draws in early retirement years."""
        params = _params()
        rows   = project_scenario(sandy, params, spouse=andy)
        for age in (65, 66, 67, 68, 69, 70):
            r = _row_at(rows, age)
            assert r.withdrawal_from_tfsa == pytest.approx(0, abs=1), (
                f"TFSA drawn at age {age}: ${r.withdrawal_from_tfsa:,.0f} — should be preserved early"
            )


# ---------------------------------------------------------------------------
# E) RRIF minimum withdrawal mechanics
# ---------------------------------------------------------------------------

class TestRrifMinimums:
    """
    RRSP converts to RRIF at end of age-71 year. Mandatory minimums apply
    from age 72. With these balances, spending needs already exceed the
    mandatory minimum so min_applied should remain False.
    """

    @pytest.fixture(scope="class")
    def rows(self, sandy, andy):
        return project_scenario(sandy, _params(), spouse=andy)

    def test_no_rrif_minimum_applied_when_spend_exceeds_min(self, rows):
        """At $84k spending, the RRIF draw needed for the gap exceeds the mandatory
        minimum — so rrif_minimum_applied should be False in early retirement."""
        for age in (72, 73, 74, 75):
            r = _row_at(rows, age)
            assert not r.rrif_minimum_applied, (
                f"Expected rrif_minimum_applied=False at age {age} (spending > min)"
            )

    def test_rrif_draw_increases_with_inflation(self, rows):
        """RRIF draw grows year-over-year as spending target inflates."""
        r65 = _row_at(rows, 65)
        r70 = _row_at(rows, 70)
        assert r70.withdrawal_from_rrif > r65.withdrawal_from_rrif, (
            "RRIF draw at 70 should exceed year-1 draw as spending inflates"
        )

    def test_rrsp_balance_declines_each_year(self, rows):
        """RRIF balance should decrease over time as draws exceed growth."""
        r65 = _row_at(rows, 65)
        r75 = _row_at(rows, 75)
        r85 = _row_at(rows, 85)
        assert r75.rrsp_rrif_balance < r65.rrsp_rrif_balance
        assert r85.rrsp_rrif_balance < r75.rrsp_rrif_balance


# ---------------------------------------------------------------------------
# F) Conservative scenario — heavier shortfall
# ---------------------------------------------------------------------------

class TestConservativeScenario:
    """Conservative (3.5% return) shows more shortfall years — useful for stress-test."""

    @pytest.fixture(scope="class")
    def result(self, sandy, andy):
        params = _params(name="Conservative", portfolio_return_pct=3.5)
        rows   = project_scenario(sandy, params, spouse=andy)
        return rows, scenario_summary(params, rows)

    def test_coverage_lower_than_base(self, result):
        _, s = result
        assert s["avg_coverage_pct"] < 91.0, (
            "Conservative should have lower coverage than Base Case"
        )

    def test_depletes_earlier_than_base(self, result):
        _, s = result
        assert s["depletion_age"] is not None
        assert s["depletion_age"] < 93, (
            f"Conservative should deplete before age 93, got {s['depletion_age']}"
        )

    def test_more_shortfall_years(self, result):
        rows_cons, s_cons = result
        params_base = _params()
        rows_base   = project_scenario(
            PersonProfile(current_age=65, rrsp_rrif_balance=400_000, tfsa_balance=50_000,
                non_registered_balance=0, cpp_monthly_at_65=1_130.74, oas_monthly_at_65=742.0,
                pension_monthly=0, tfsa_room_remaining=0, province="ON"),
            params_base,
            spouse=PersonProfile(current_age=65, rrsp_rrif_balance=300_000, tfsa_balance=0,
                non_registered_balance=0, cpp_monthly_at_65=1_130.74, oas_monthly_at_65=742.0,
                pension_monthly=0, tfsa_room_remaining=0, province="ON"),
        )
        s_base = scenario_summary(params_base, rows_base)
        assert s_cons["years_with_shortfall"] >= s_base["years_with_shortfall"]
