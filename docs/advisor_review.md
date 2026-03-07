# Auri — Senior Investment Advisor Review
**Date:** March 2026
**Scope:** Full application review covering investment methodology, analytical depth, counter-opinion capability, and UI/UX usability
**Reviewer perspective:** Senior investment advisor with wealth management background

---

## Executive Summary

Auri is a well-constructed personal portfolio intelligence tool that covers the core workflow a self-directed investor needs: position tracking, risk profiling, target allocation, and policy compliance. The architecture is sound, the privacy posture (offline by default, gitignored sensitive files) is genuinely thoughtful, and the technical execution is clean. For a personal tool at this stage, it delivers real advisory value.

The gaps are not in what it does — they are in what it does not challenge. As it stands, the app is an excellent *mirror* of your current portfolio but not yet a *counterpart* that pushes back, surfaces blind spots, or generates independent views. That distinction matters in practice.

---

## 1. Investment Methodology

### 1.1 Risk Scoring

**What works well:**
The seven-question questionnaire covers the core dimensions that professional suitability processes use: investment objective, time horizon, drawdown tolerance, loss reaction, liquidity needs, and legacy intent. The weighted scoring approach is conceptually correct. Mapping to five profile labels (Conservative through Aggressive) with a numerical score is standard and appropriate.

**Gaps and concerns:**

**Static tier mapping.** The risk score produces one of four hard allocation templates with no interpolation. A score of 30 (Conservative) and a score of 31 (Moderate) produce materially different allocations despite being functionally identical investors. In practice, allocations should blend continuously across the tier boundary.

**No life-stage context.** The questionnaire does not distinguish between a 35-year-old growth investor accumulating capital and a 70-year-old growth investor who has been retired for five years. Both could score 65/100. Their appropriate allocations are very different. Age and retirement status should be weighted inputs, not just free-text fields.

**Drawdown tolerance is not back-tested against the portfolio.** The profile records that you can tolerate a 20% drawdown, but the app never computes the *actual* drawdown your current portfolio would have experienced in 2020 or 2022. That gap makes the tolerance figure decorative rather than actionable.

**The score is not updated automatically.** If the portfolio drifts significantly from the target, the risk score can become stale without any notification. A "score last computed X days ago" warning when the score is older than 90 days would be appropriate.

---

### 1.2 Target Allocation Templates

**What works well:**
The four Canadian-market templates are sensible starting points. The sector labels (Equities - Canada, Equities - US, Fixed Income, Financials, Energy, etc.) are appropriate for a TSX/NYSE mixed portfolio. The in-app editor with live sum validation makes the templates genuinely useful rather than illustrative.

**Gaps and concerns:**

**Templates do not include international or alternatives.** A Canadian investor's growth portfolio with 25% Equities - Canada and 30% Equities - US is meaningfully underexposed to Europe, Emerging Markets, and Asia. A 70/100 growth investor should arguably carry 10–15% international developed and 5% emerging markets. The current templates embed a significant home-country and US bias that should be disclosed, not silent.

**Fixed Income is a single bucket.** The 50% Fixed Income allocation for a Conservative investor conflates very different instruments: GICs, Canadian federal bonds, provincial bonds, corporate bonds, and bond ETFs all have different duration, credit, and liquidity profiles. A 5-year laddered GIC portfolio is not the same risk as a long-duration bond ETF when rates rise. The current model cannot distinguish them.

**Energy at a flat 5% across all profiles is under-considered.** For a Canadian retail investor, Energy is often one of the largest natural tilts given TSX composition. A fixed 5% ignores whether the investor already has concentrated Energy through employer equity or pension exposure. The app has no concept of *total* Energy exposure including what is not in this portfolio.

**Rebalancing amount is gross, not tax-adjusted.** The "Rebalancing Trades" section shows the gross dollar amount required. A sell in a non-registered account triggers a capital gains event; a sell in a TFSA does not. The recommendation to "Sell Fixed Income — $42,000" means something very different depending on which account type it sits in. This is the single most consequential missing analytical layer.

---

### 1.3 Concentration and Policy Compliance

**What works well:**
The 10% single-position threshold for concentration flags is the standard starting point used in most advisory contexts. The policy engine (max position, max sector, excluded sectors, warnings at 85% of limit) is well-designed and useful.

**Gaps:**

**Concentration is measured at the position level, not the economic exposure level.** If you hold BCE, Telus, and a Canadian Dividend ETF that itself holds 15% BCE, your *effective* BCE exposure is invisible to the current system. Look-through concentration for ETFs/funds is a meaningful capability gap.

**No correlated-risk grouping.** A portfolio holding Royal Bank, TD, BMO, and a Canadian Financials ETF is heavily concentrated in the Canadian banking sector even if no single position exceeds 10%. The current model would show four positions under the threshold. A sector-level correlated exposure view would surface this.

**Policy constraints are self-defined, not benchmarked.** The user sets their own max sector at 40%. There is no external reference for whether 40% is reasonable given their profile, and no flag if the constraint itself is inconsistent with their stated risk score.

---

## 2. Insight Quality

### 2.1 Portfolio Commentary (AI-Generated)

**What works well:**
Surfacing an on-demand AI commentary is genuinely useful and differentiated from static dashboards. Passing the investment philosophy narrative into the prompt creates meaningful personalization. The provider/prompt-length attribution is a nice transparency touch.

**Gaps:**

**The commentary is a summary, not an analysis.** As currently structured, the AI is given the portfolio snapshot and asked to describe it. A senior advisor does not summarize what they can already see — they identify what is *wrong* with it, what is missing, and what should change. The prompt should be structured to force the AI to produce:
- Three specific risks the portfolio is currently running that the investor may not be aware of
- Two allocation changes the advisor would recommend and why
- One position the advisor would examine for replacement and what the alternative thesis would be

**No source citation or reasoning chain.** The commentary output does not distinguish between observations (your portfolio is X% Fixed Income) and judgments (this is appropriate/inappropriate given your profile). An advisor's commentary should be explicit about the *basis* for each recommendation.

**Commentary does not update when targets change.** If the user saves new targets and the portfolio is now significantly under-allocated to equities, the commentary from yesterday remains unchanged until manually regenerated. A staleness indicator on the commentary ("Generated before last target change") would improve trust.

---

### 2.2 Income View

**What works well:**
The dividend yield and estimated annual income layer is practically useful and correctly separated from cost-basis P&L. Using live Yahoo Finance prices rather than CSV values makes the income figures reliable.

**Gaps:**

**Income is not split between registered and non-registered accounts.** Dividend income in a TFSA is tax-free; in a non-registered account it generates a T5 slip. The income tab shows total income but cannot answer "how much of my income will I owe tax on?" — which is the question that matters.

**No income target or coverage ratio.** If the investor's retirement expenses are $80,000/year and the portfolio generates $24,000 in dividend income, the coverage ratio is 30%. That number — and how it trends across snapshots — is one of the most important metrics a retiree tracks. It exists nowhere in the current application.

**Distribution reinvestment is not modeled.** All income is shown as yield; there is no DRIP (Dividend Reinvestment Plan) modeling or compound growth projection.

---

## 3. Counter-Opinion Capability

This is the most significant gap in the current application.

The app reflects the investor's own views back at them with more precision. It does not challenge those views.

### 3.1 What is missing

**Devil's advocate mode.** When the investor saves a target allocation, the system has no mechanism to say: "Your 30% allocation to Equities - Canada is above what most professional managers recommend for a Canadian investor seeking global diversification. Peer portfolios at your risk level average 18–22% Canada equity. Here is the case for and against your position."

**Alternative security suggestions.** If BCE is flagged as a concentration risk, there is no capability to suggest "you might consider trimming BCE and adding Telus or a Dividend ETF to maintain telecom exposure with less single-stock risk." The AI commentary could do this if the prompt were structured to request it explicitly.

**Benchmark comparison.** There is no reference portfolio. The investor does not know whether their 9.2% unrealized gain is outstanding, in line with, or lagging a relevant benchmark (e.g. XIU for a Canadian equity-tilted portfolio, XBAL for a balanced portfolio). Without a benchmark, every number is context-free.

**Scenario analysis.** A rate increase of 100bps would affect your Fixed Income allocation by approximately X%. A 20% TSX correction would reduce your portfolio value by approximately Y%. These are the questions an advisor fields most often and they are entirely absent.

**Contrarian macro view.** The current commentary prompt likely generates conventional analysis. A senior advisor adds value by bringing in a view that challenges consensus — e.g., "You are 40% Financials + Energy in a portfolio where interest rates may decline and oil faces long-term demand headwinds. Here is the bear case for your two largest sector bets."

### 3.2 How to address it

The commentary engine is the natural home for this. The simplest upgrade is structured prompt engineering:
- Replace the open-ended summary prompt with a structured output format
- Require the AI to produce: risks, alternatives, benchmark comparison, one contrarian take
- Add a "Challenge my portfolio" mode distinct from the standard commentary

A second approach is a dedicated "Second Opinion" page that calls the AI with a different system prompt framed as a skeptical analyst rather than a supportive summarizer.

---

## 4. UI/UX Review

### 4.1 Navigation and Information Architecture

**What works well:**
The page structure (Home, Analysis, Snapshots, Profile, Health) covers the main workflow. The Home page drift banner is exactly the right pattern — actionable, contextual, and linked to the resolution path.

**Friction points:**

**Page naming does not convey purpose.** The sidebar shows "5_Analysis" with the number prefix visible. Page 5 of what? A user arriving for the first time would not know what "Analysis" contains versus what "Home" contains. The naming should be: "Dashboard", "Analysis", "History", "My Profile", "System". The current naming is developer-oriented, not advisor-oriented.

**The workflow is not linear but the UI is not opinionated about sequence.** A first-time user needs to: (1) upload a CSV, (2) complete the risk questionnaire, (3) generate a target allocation, (4) review their position against targets. Nothing guides them through this. An onboarding checklist or wizard that surfaces the "next required step" would eliminate the most common confusion.

**The Risk Profile page is buried.** It is one of the most important inputs in the system but sits at the bottom of the sidebar with no prominence. It should be closer to the top, possibly with a completion status indicator visible in the sidebar.

**Commentary and Analysis are split across multiple actions.** A user wanting a full picture of their portfolio needs to: go to Home, press "Refresh Prices", go to Analysis, press "Generate Commentary", review targets, go to Snapshots for history. The critical-path actions could be consolidated.

### 4.2 Data Tables

**What works well:**
The tab structure on the Positions table (Holdings / Income / P&L / Accounts) is well-organized and prevents information overload. Column formatting for dollar values and percentages is appropriate.

**Friction points:**

**Sortable columns are not always obvious.** Streamlit's dataframes are sortable by click, but there is no affordance indicating which column is the current sort key. A user comparing positions by unrealized gain may not discover they can click the column header.

**The Target Allocation table does not highlight the actions with the largest dollar impact.** The rebalancing trades are sorted by absolute dollar amount, which is correct. But the color-coded table above it uses equal cell highlighting for a $500 deviation and a $50,000 deviation. The visual weight should match the decision weight.

**The sector bar chart on Home uses an alphabetical X-axis.** The chart is much more useful if sorted by weight descending, which immediately shows what dominates the portfolio. This applies to both the Home sector chart and the Analysis actual vs target chart.

### 4.3 Mobile and Screen Size

The `layout="wide"` configuration is appropriate for a desktop tool but tables will overflow on smaller screens. If this is ever used on a tablet, the multi-column layouts will compress badly. Not a current priority but worth flagging.

---

## 5. Overall Assessment

| Dimension | Rating | Comment |
|---|---|---|
| Portfolio data quality | Strong | Cost basis, unrealized gain, three-bucket classification, reconciliation — all correct |
| Risk profiling | Adequate | Covers the basics; missing life-stage weighting and auto-staleness detection |
| Target allocation | Adequate | Sensible templates; missing tax-location logic and international exposure |
| Rebalancing guidance | Adequate | Correct math; needs tax-context before acting on recommendations |
| Income analysis | Good | Live yield + income is practical; missing coverage ratio and tax split |
| Concentration monitoring | Good | Position and sector flags work; missing look-through for ETFs |
| Commentary | Developing | Personalized but descriptive; needs structured adversarial prompt |
| Counter-opinion capability | Not present | Largest gap; no challenge mode, no benchmark, no scenario analysis |
| UI navigation | Adequate | Functional; developer-flavored naming; no onboarding path |
| UI data presentation | Good | Tab structure and filtering are well-executed; sort affordance is weak |

---

## 6. Recommended Next Steps (Prioritized)

**Priority 1 — Tax-aware rebalancing**
Before acting on any trade recommendation, the user needs to know whether the sell is in a registered (tax-sheltered) or non-registered (taxable) account. This is the single highest-value improvement because it directly affects decisions that have real financial consequences.

**Priority 2 — Structured advisory commentary prompt**
Redesign the commentary prompt to produce structured output: risks, recommendations, alternatives, one contrarian view. Add a "Challenge my portfolio" toggle that uses a skeptical analyst framing. This transforms the commentary from a description into actual advice.

**Priority 3 — Income coverage ratio**
Compute annual portfolio income / annual retirement expenses and track it across snapshots. This is the number a retiree cares about most and it currently requires mental arithmetic to derive.

**Priority 4 — Benchmark comparison**
Allow the user to select a reference benchmark (XIU, XBAL, XGRO, custom) and compute trailing performance vs. benchmark. Even a simple delta is more useful than an absolute return without context.

**Priority 5 — Onboarding path**
Add a setup checklist or status widget that tells a new user: "You are missing: (1) risk score, (2) target allocation." This eliminates the most common confusion about where to start.

**Priority 6 — International allocation in templates**
Add Equities - International Developed (10–15%) and Equities - Emerging Markets (0–5%) to the Growth and Aggressive templates. The current templates encode a home-country + US bias that most professional allocators would flag.

**Priority 7 — Scenario stress test**
Add a simple stress-test panel: select a scenario (rate +1%, equity -20%, energy -30%) and see the estimated portfolio impact given current weights. This can be entirely rules-based and does not require real market data.

---

*This review is based on code analysis of the application as of March 2026. It reflects an advisory perspective on investment methodology and user experience, not a compliance or regulatory assessment.*
