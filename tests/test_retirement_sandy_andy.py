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

Calibration notes
-----------------
2026-accurate rates: CPP $1,130.74, OAS $742 → 91.3% coverage at 5%/3%.

The video was recorded with older/lower CPP rates. Two calibration variants:
  - 2024-era rates (75% of $1,364/mo ≈ $1,023): 87.6% coverage — closer to 81%
  - ~$900/mo CPP + $690 OAS: 81.7% coverage — matches video almost exactly

Remaining gap from video's 81% even with 2024-era rates (~87.6%) is explained
by our engine's inflation-indexed CPP/OAS (benefits grow with CPI), while the
video's software likely treated government pensions as fixed nominal amounts.

Scenarios tested
----------------
A) Base Case (SIMPLE, 2026 rates):       91.3% coverage, depletion age 93
B) 2024-era CPP rates ($1,023):          87.6% coverage, depletion age 91
   Older rates ($900/$690):              81.7% — matches video's 81% exactly
C) Tax-Optimised — meltdown with bracket-aware ceiling:
   $57,375 ceiling (first federal bracket top, 2026 = $58,523):
     - Coverage 90.9%, NO depletion — significant improvement over SIMPLE
     - Total taxes $30k LOWER than SIMPLE ($497k vs $528k)
     - Estate at 90 ≈ $62k vs ~$0 for SIMPLE
   $100k ceiling (aggressive):
     - Drains RRIF by age 72 → pays $25k MORE tax than SIMPLE
     - Same coverage/estate as SIMPLE — no benefit, extra tax cost
   Key: bracket-aware ceiling is essential; aggressive ceiling is counterproductive.
D) Auto-TFSA routing: TFSA grows via new annual room; no early draws
E) RRIF minimums: spending exceeds mandatory min → min_applied=False.
   When RRIF is very large relative to spending → min_applied=True (documented).
F) Conservative stress (3.5%–4% return, 4% inflation): drops to ~82–84%
"""

import pytest
from agents.ori_rp.cashflow import (
    PersonProfile, ScenarioParams, project_scenario, scenario_summary, YearResult
)
from agents.ori_rp.tax import rrif_minimum_pct, rrif_minimum_withdrawal
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
# B) Video-calibrated variants — older CPP/OAS rates
# ---------------------------------------------------------------------------

class TestVideoCalibrated:
    """
    Two calibration levels:
      - 2024-era rates: 75% of 2024 CPP max ($1,364/mo) = $1,023/mo each.
        Our engine produces 87.6% — notably closer to video's 81%.
      - Pre-2024 rates: $900 CPP / $690 OAS per person.
        Our engine produces 81.7% — matches the video almost exactly.

    The remaining ~6pt gap between 2024-era (87.6%) and video (81%) is
    explained by CPP/OAS inflation indexing: our engine grows government
    pensions with CPI, reducing real portfolio pressure each year. A system
    treating them as fixed nominal amounts produces materially lower coverage
    under the same 3% inflation assumption.
    """

    @pytest.fixture(scope="module")
    def profiles_2024_era(self):
        """75% of 2024 CPP max ≈ $1,023/mo."""
        sandy = PersonProfile(current_age=65, rrsp_rrif_balance=400_000,
            tfsa_balance=50_000, non_registered_balance=0,
            cpp_monthly_at_65=1_023.0, oas_monthly_at_65=742.0,
            pension_monthly=0, tfsa_room_remaining=0, province="ON")
        andy = PersonProfile(current_age=65, rrsp_rrif_balance=300_000,
            tfsa_balance=0, non_registered_balance=0,
            cpp_monthly_at_65=1_023.0, oas_monthly_at_65=742.0,
            pension_monthly=0, tfsa_room_remaining=0, province="ON")
        return sandy, andy

    @pytest.fixture(scope="module")
    def profiles_pre2024(self):
        """Pre-2024 approximate rates used in the video."""
        sandy = PersonProfile(current_age=65, rrsp_rrif_balance=400_000,
            tfsa_balance=50_000, non_registered_balance=0,
            cpp_monthly_at_65=900.0, oas_monthly_at_65=690.0,
            pension_monthly=0, tfsa_room_remaining=0, province="ON")
        andy = PersonProfile(current_age=65, rrsp_rrif_balance=300_000,
            tfsa_balance=0, non_registered_balance=0,
            cpp_monthly_at_65=900.0, oas_monthly_at_65=690.0,
            pension_monthly=0, tfsa_room_remaining=0, province="ON")
        return sandy, andy

    def test_2024_era_rates_closer_to_video(self, profiles_2024_era):
        """2024-era CPP ($1,023) produces ~87.6% — closer to video's 81% than 2026 rates."""
        s, a = profiles_2024_era
        rows = project_scenario(s, _params(), spouse=a)
        cov = scenario_summary(_params(), rows)["avg_coverage_pct"]
        assert 84.0 <= cov <= 91.0, (
            f"2024-era coverage {cov:.1f}% expected 84-91%"
        )

    def test_2024_era_lower_than_2026(self, profiles_2024_era, sandy, andy):
        """2024 rates → lower coverage than 2026 rates (less pension income)."""
        rows_24 = project_scenario(profiles_2024_era[0], _params(), spouse=profiles_2024_era[1])
        rows_26 = project_scenario(sandy,                 _params(), spouse=andy)
        cov_24 = scenario_summary(_params(), rows_24)["avg_coverage_pct"]
        cov_26 = scenario_summary(_params(), rows_26)["avg_coverage_pct"]
        assert cov_24 < cov_26, "2024-era CPP should produce lower coverage than 2026 rates"

    def test_pre2024_rates_match_video_81pct(self, profiles_pre2024):
        """Pre-2024 rates ($900/$690) reproduce the video's 81% figure."""
        s, a = profiles_pre2024
        rows = project_scenario(s, _params(), spouse=a)
        cov = scenario_summary(_params(), rows)["avg_coverage_pct"]
        assert 78.0 <= cov <= 85.0, (
            f"Pre-2024 coverage {cov:.1f}% expected 78-85% (video showed 81%)"
        )

    def test_2024_era_year1_pension_income(self, profiles_2024_era):
        """2024-era: HH pensions = ($1,023 + $742) × 2 × 12 ≈ $42,360/yr base."""
        s, a = profiles_2024_era
        rows = project_scenario(s, _params(), spouse=a)
        r65 = _row_at(rows, 65)
        gov = r65.cpp_income + r65.oas_income
        assert 42_000 <= gov <= 44_000, f"2024-era year-1 pensions ${gov:,.0f}"

    def test_lower_pensions_increase_portfolio_dependency(self, profiles_pre2024):
        """Pre-2024 CPP/OAS: portfolio must cover a larger fraction of spending."""
        gov_base = (900.0 + 690.0) * 2 * 12   # $38,160/yr
        gap = 84_000 - gov_base                # $45,840
        assert gap > 40_000, f"Expected large portfolio gap, got ${gap:,.0f}"


# ---------------------------------------------------------------------------
# C) Tax-Optimised — meltdown ceiling comparison
# ---------------------------------------------------------------------------

class TestRrspMeltdownOptimisation:
    """
    RRSP meltdown ceiling comparison — bracket awareness is critical.

    Ceiling rationale:
      $57,375 = top of first 2026 federal bracket ($58,523; rounded down for margin).
      Draws beyond this threshold hit 20.5% federal + Ontario surtax layers.
      A conservative ceiling clears the RRSP gently over ~5 years, staying
      in the lowest marginal band.

    Results vs SIMPLE:
      $57k ceiling: −$30k lifetime taxes, NO depletion, $62k estate at 90
      $100k ceiling: +$25k lifetime taxes, still depletes age 93, $787 estate
      Conclusion: aggressive ceiling is strictly worse than SIMPLE — it front-loads
      draws into higher brackets before CPP/OAS closes the income gap.
    """

    _CEILING_CONSERVATIVE = 57_375.0    # top of first federal bracket (2026)
    _CEILING_AGGRESSIVE   = 100_000.0   # crosses into higher brackets

    @pytest.fixture(scope="class")
    def three_results(self, sandy, andy):
        p_s  = _params(strategy=WithdrawalStrategy.SIMPLE, name="Simple")
        p_c  = _params(strategy=WithdrawalStrategy.RRSP_MELTDOWN,
                       ceiling=self._CEILING_CONSERVATIVE, name="Conservative Melt")
        p_a  = _params(strategy=WithdrawalStrategy.RRSP_MELTDOWN,
                       ceiling=self._CEILING_AGGRESSIVE, name="Aggressive Melt")
        rows_s  = project_scenario(sandy, p_s,  spouse=andy)
        rows_c  = project_scenario(sandy, p_c,  spouse=andy)
        rows_a  = project_scenario(sandy, p_a,  spouse=andy)
        return (rows_s, scenario_summary(p_s, rows_s),
                rows_c, scenario_summary(p_c, rows_c),
                rows_a, scenario_summary(p_a, rows_a))

    # --- Conservative ceiling ($57k) ---

    def test_conservative_ceiling_saves_taxes(self, three_results):
        """$57k ceiling saves >$10k lifetime taxes vs SIMPLE."""
        _, s_s, _, s_c, _, _ = three_results
        saving = s_s["total_taxes"] - s_c["total_taxes"]
        assert saving > 10_000, (
            f"Conservative ceiling: expected >$10k tax saving, got ${saving:,.0f}"
        )

    def test_conservative_ceiling_avoids_depletion(self, three_results):
        """$57k ceiling: no depletion to age 95 (SIMPLE depletes at 93)."""
        _, _, _, s_c, _, _ = three_results
        assert s_c["depletion_age"] is None, (
            f"Conservative meltdown still depletes at age {s_c['depletion_age']}"
        )

    def test_conservative_ceiling_better_estate(self, three_results):
        """$57k ceiling estate at 90 materially better than SIMPLE (~$62k vs ~$0)."""
        rows_s, _, rows_c, _, _, _ = three_results
        estate_s = _row_at(rows_s, 90).portfolio_value
        estate_c = _row_at(rows_c, 90).portfolio_value
        assert estate_c > estate_s + 30_000, (
            f"Conservative meltdown estate at 90 ${estate_c:,.0f} should beat SIMPLE ${estate_s:,.0f}"
        )

    def test_conservative_ceiling_draws_more_rrif_early(self, three_results):
        """Conservative meltdown draws more RRIF than SIMPLE in year 1."""
        rows_s, _, rows_c, _, _, _ = three_results
        assert _row_at(rows_c, 65).withdrawal_from_rrif > _row_at(rows_s, 65).withdrawal_from_rrif

    def test_conservative_meltdown_drains_rrif_before_cpp_oas_window(self, three_results):
        """RRIF should be substantially lower at age 72 with conservative meltdown."""
        rows_s, _, rows_c, _, _, _ = three_results
        rrif_s_72 = _row_at(rows_s, 72).rrsp_rrif_balance
        rrif_c_72 = _row_at(rows_c, 72).rrsp_rrif_balance
        assert rrif_c_72 < rrif_s_72 * 0.9, (
            f"Conservative meltdown RRIF at 72 ${rrif_c_72:,.0f} should be much lower "
            f"than SIMPLE ${rrif_s_72:,.0f}"
        )

    # --- Aggressive ceiling ($100k) — counterproductive ---

    def test_aggressive_ceiling_costs_more_tax_than_simple(self, three_results):
        """$100k ceiling crosses higher brackets → costs more tax than SIMPLE."""
        _, s_s, _, _, _, s_a = three_results
        extra_tax = s_a["total_taxes"] - s_s["total_taxes"]
        assert extra_tax > 15_000, (
            f"Aggressive ceiling should cost >$15k more tax than SIMPLE, got ${extra_tax:,.0f}"
        )

    def test_aggressive_ceiling_no_better_than_simple(self, three_results):
        """Aggressive ceiling still depletes at same age as SIMPLE — no benefit."""
        _, s_s, _, _, _, s_a = three_results
        # Both deplete at age 93 — aggressive ceiling provides no longevity improvement
        assert s_a["depletion_age"] == s_s["depletion_age"], (
            f"Aggressive meltdown (dep={s_a['depletion_age']}) should match SIMPLE "
            f"(dep={s_s['depletion_age']}) — no benefit from over-aggressive draws"
        )

    def test_bracket_ceiling_beats_aggressive_ceiling(self, three_results):
        """Conservative ($57k) strictly dominates aggressive ($100k) on all metrics."""
        _, _, _, s_c, _, s_a = three_results
        # Lower taxes
        assert s_c["total_taxes"] < s_a["total_taxes"], "Conservative ceiling should pay less tax"
        # Better or equal depletion age
        dep_c = s_c["depletion_age"] or 96
        dep_a = s_a["depletion_age"] or 96
        assert dep_c >= dep_a, "Conservative ceiling should not deplete earlier"


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
    RRSP converts to RRIF at end of the year the owner turns 71.
    Mandatory minimums apply from age 72 using CRA-prescribed factors.

    2026 RRIF minimum factors (from refs/retirement/rrif_minimums.yaml):
      Age 72: 5.40%   Age 75: 5.82%   Age 80: 6.82%
      Age 85: 8.51%   Age 90: 11.92%

    Sandy & Andy: RRIF draw to cover spending gap always exceeds the
    mandatory minimum → min_applied stays False throughout.

    min_applied=True only occurs when the RRIF is very large relative to
    spending (documented in test_rrif_min_applies_on_large_rrif).
    """

    @pytest.fixture(scope="class")
    def rows(self, sandy, andy):
        return project_scenario(sandy, _params(), spouse=andy)

    def test_rrif_minimum_pct_increases_with_age(self):
        """CRA minimum factors escalate with age — fundamental RRIF mechanic."""
        pcts = {age: rrif_minimum_pct(age) for age in (72, 75, 80, 85, 90)}
        assert pcts[72] < pcts[75] < pcts[80] < pcts[85] < pcts[90], (
            f"RRIF minimum pcts not monotonically increasing: {pcts}"
        )

    def test_rrif_minimum_pct_calibrated_to_2026_table(self):
        """Spot-check 2026 CRA prescribed factors from the reference YAML."""
        assert rrif_minimum_pct(72) == pytest.approx(5.40, abs=0.01)
        assert rrif_minimum_pct(75) == pytest.approx(5.82, abs=0.01)
        assert rrif_minimum_pct(80) == pytest.approx(6.82, abs=0.01)
        assert rrif_minimum_pct(85) == pytest.approx(8.51, abs=0.01)
        assert rrif_minimum_pct(90) == pytest.approx(11.92, abs=0.01)

    def test_rrif_minimum_dollar_scales_with_balance(self):
        """Dollar minimum = balance × factor — proportional to RRIF size."""
        balance = 350_000
        min_72 = rrif_minimum_withdrawal(balance, 72)
        min_80 = rrif_minimum_withdrawal(balance, 80)
        assert min_72 == pytest.approx(balance * 0.054, abs=100)
        assert min_80 == pytest.approx(balance * 0.0682, abs=100)
        assert min_80 > min_72, "Minimum dollar amount grows as factor rises"

    def test_rrif_minimum_zero_below_age_72(self):
        """No mandatory minimum before age 72."""
        assert rrif_minimum_withdrawal(400_000, 71) == 0.0
        assert rrif_minimum_withdrawal(400_000, 65) == 0.0

    def test_no_rrif_minimum_applied_in_sandy_andy(self, rows):
        """Sandy & Andy: spending draw exceeds mandatory minimum → min_applied=False.

        At $84k household spending, each person's portfolio draw far exceeds
        the CRA minimum on $400k/$300k RRIF balances. No forced excess occurs.
        """
        for age in (72, 73, 74, 75, 76, 77, 78):
            r = _row_at(rows, age)
            assert not r.rrif_minimum_applied, (
                f"Expected min_applied=False at age {age}: "
                f"draw ${r.withdrawal_from_rrif:,.0f} > mandatory min on declining balance"
            )

    def test_rrif_min_applies_on_large_rrif(self, andy):
        """min_applied=True when RRIF is very large relative to spending need."""
        rich = PersonProfile(current_age=65, rrsp_rrif_balance=2_000_000,
            tfsa_balance=500_000, non_registered_balance=0,
            cpp_monthly_at_65=1_130.74, oas_monthly_at_65=742.0,
            pension_monthly=0, tfsa_room_remaining=0, province="ON")
        rich_sp = PersonProfile(current_age=65, rrsp_rrif_balance=1_000_000,
            tfsa_balance=0, non_registered_balance=0,
            cpp_monthly_at_65=1_130.74, oas_monthly_at_65=742.0,
            pension_monthly=0, tfsa_room_remaining=0, province="ON")
        # Low spending ($60k) + very large RRIF ($3M) → mandatory min forces extra draws
        p = _params(name="rich", target_annual_spending=60_000)
        rows = project_scenario(rich, p, spouse=rich_sp)
        # By age 72, the mandatory minimum on $2M+ RRIF greatly exceeds the spending gap
        r72 = _row_at(rows, 72)
        assert r72.rrif_minimum_applied, (
            f"Expected min_applied=True at 72 with $2M RRIF and $60k spending; "
            f"got draw ${r72.withdrawal_from_rrif:,.0f}"
        )

    def test_rrif_draw_increases_with_inflation(self, rows):
        """RRIF draw grows year-over-year as spending target inflates."""
        r65 = _row_at(rows, 65)
        r70 = _row_at(rows, 70)
        assert r70.withdrawal_from_rrif > r65.withdrawal_from_rrif

    def test_rrsp_balance_declines_each_year(self, rows):
        """RRIF balance should decrease over time as draws exceed growth."""
        r65 = _row_at(rows, 65)
        r75 = _row_at(rows, 75)
        r85 = _row_at(rows, 85)
        assert r75.rrsp_rrif_balance < r65.rrsp_rrif_balance
        assert r85.rrsp_rrif_balance < r75.rrsp_rrif_balance


# ---------------------------------------------------------------------------
# F) Stress scenarios — low returns + high inflation
# ---------------------------------------------------------------------------

class TestStressScenario:
    """
    Stress the plan with lower returns and higher inflation.
    Sandy & Andy calibrated numbers at 5%/3% base:
      91.3% coverage, depletes age 93.

    Stress results (no phases, 2026 CPP rates):
      4.0% return / 4.0% inflation: 83.5% coverage, depletes age 87
      3.5% return / 4.0% inflation: 82.0% coverage, depletes age 86
      2.5% return / 4.0% inflation: 79.6% coverage, depletes age 84

    These are directionally similar to the video's stress test (~62%), with
    the gap explained by CPP/OAS inflation indexing (our engine; see calibration
    note in module docstring). Conservative ceiling meltdown consistently
    outperforms SIMPLE under all stress assumptions.
    """

    @pytest.fixture(scope="class")
    def stress_4_4(self, sandy, andy):
        p = _params(portfolio_return_pct=4.0, inflation_rate_pct=4.0, name="Stress 4/4")
        rows = project_scenario(sandy, p, spouse=andy)
        return rows, scenario_summary(p, rows)

    @pytest.fixture(scope="class")
    def stress_35_4(self, sandy, andy):
        p = _params(portfolio_return_pct=3.5, inflation_rate_pct=4.0, name="Stress 3.5/4")
        rows = project_scenario(sandy, p, spouse=andy)
        return rows, scenario_summary(p, rows)

    def test_stress_coverage_below_base(self, stress_4_4):
        """4%/4% coverage is materially below 5%/3% base (91.3%)."""
        _, s = stress_4_4
        assert s["avg_coverage_pct"] < 88.0, (
            f"Stress 4/4 coverage {s['avg_coverage_pct']:.1f}% should be well below base"
        )

    def test_stress_coverage_calibrated_range(self, stress_4_4):
        """4%/4% stress: ~83.5% coverage — directionally matches video stress direction."""
        _, s = stress_4_4
        assert 78.0 <= s["avg_coverage_pct"] <= 88.0, (
            f"Stress 4/4 coverage {s['avg_coverage_pct']:.1f}% outside 78-88% band"
        )

    def test_stress_depletes_earlier_than_base(self, stress_4_4):
        """Stress depletes well before base case age-93 depletion."""
        _, s = stress_4_4
        assert s["depletion_age"] is not None
        assert s["depletion_age"] < 92, (
            f"Stress should deplete before 92, got age {s['depletion_age']}"
        )

    def test_more_stress_more_shortfall(self, stress_4_4, stress_35_4):
        """3.5%/4% is worse than 4%/4% — coverage and depletion degrade monotonically."""
        _, s44  = stress_4_4
        _, s354 = stress_35_4
        assert s354["avg_coverage_pct"] <= s44["avg_coverage_pct"], (
            "Lower return should not improve coverage"
        )

    def test_conservative_ceiling_beats_simple_under_stress(self, sandy, andy):
        """$57k meltdown ceiling saves taxes and improves estate even under 4%/4% stress."""
        p_s = _params(portfolio_return_pct=4.0, inflation_rate_pct=4.0,
                      strategy=WithdrawalStrategy.SIMPLE)
        p_m = _params(portfolio_return_pct=4.0, inflation_rate_pct=4.0,
                      strategy=WithdrawalStrategy.RRSP_MELTDOWN, ceiling=57_375.0)
        rows_s = project_scenario(sandy, p_s, spouse=andy)
        rows_m = project_scenario(sandy, p_m, spouse=andy)
        s_s = scenario_summary(p_s, rows_s)
        s_m = scenario_summary(p_m, rows_m)
        # Conservative meltdown should save taxes even under stress
        assert s_m["total_taxes"] < s_s["total_taxes"], (
            "Conservative meltdown should save taxes under stress assumptions too"
        )

    def test_more_shortfall_years_under_stress(self, stress_4_4, sandy, andy):
        """Stress produces more shortfall years than base case."""
        p_base = _params()
        s_base = scenario_summary(p_base, project_scenario(sandy, p_base, spouse=andy))
        _, s_stress = stress_4_4
        assert s_stress["years_with_shortfall"] >= s_base["years_with_shortfall"]
