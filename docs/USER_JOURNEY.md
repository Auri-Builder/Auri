# Auri — User Journey & Usability Validation

---

## Purpose

A step-by-step flow map for testing Auri end-to-end with real data.
Use this to validate the navigation, data entry, and agent outputs on each session.

---

## Who this covers

- **Jeff** (primary user, BC investor, TD WebBroker, retirement planning horizon)
- **Son** (accumulation phase, Wealth Builder focus)
- **Future** — dad and Paul (advisor) via packaged release

---

## Phase 0 — Prerequisites

Before launching Auri:

- [ ] Download CSV holdings exports from TD WebBroker for each account
  - Filename pattern: `{ACCOUNTID}-holdings-{date}.csv`
  - One CSV per account (RRSP, TFSA, non-reg, etc.)
- [ ] Confirm Groq API key is available (or Claude/OpenAI if switching)
- [ ] `streamlit run Home.py` from `/home/cplus/auri`

**Validation:** App loads, sidebar shows Hub / Agents / Tools groups.

---

## Phase 1 — Setup Wizard

**Entry:** Sidebar → Tools → Setup Wizard (or Hub banner → Upload Wizard)

### 1a. CSV Upload

- [ ] Upload first CSV — confirm auto-detected account ID matches TD filename
- [ ] Set account type (RRSP / TFSA / Non-Reg / etc.) for each account
- [ ] Set currency (CAD / USD)
- [ ] Repeat for each account CSV
- [ ] Click "Save to accounts.yaml"

**Validation:**
- Hub banner "Portfolio CSV uploaded" shows ✅
- No parse errors or missing columns reported
- Correct number of positions loaded per account

### 1b. AI Provider

- [ ] Select Groq, enter API key
- [ ] Save

**Validation:**
- Hub banner "AI provider configured" shows ✅
- Hub footer shows "AI: Groq"

### 1c. Personal Profile (shared_profile.yaml)

- [ ] Enter name, province (BC), date of birth
- [ ] Save

**Validation:**
- Hub banner "Personal profile set up" shows ✅

### 1d. Wealth Builder Profile

- [ ] Enter age, income, savings rate, target retirement age, risk tolerance
- [ ] Enter RRSP / TFSA balances (or confirm auto-loaded from CSV)
- [ ] Save

**Validation:**
- Hub banner "Wealth Builder profile entered" shows ✅
- Hub Wealth Builder card shows years-to-retirement and savings rate

---

## Phase 2 — Portfolio Intelligence

**Entry:** Sidebar → Agents → Portfolio (or Hub card → Dashboard)

> Requires: CSV uploaded + investor questionnaire scored

### 2a. Investor Profile / Questionnaire

- [ ] Navigate to Investor Profile (Tools or Hub card prompt)
- [ ] Answer all questionnaire questions
- [ ] Click "Run Scorer"
- [ ] Confirm risk score saved

**Validation:**
- Hub card shows Dashboard + Analysis links (unlocked)
- Profile shows risk category (e.g. "Balanced", "Growth")

### 2b. Portfolio Dashboard

- [ ] Confirm total market value matches expectations
- [ ] Confirm position count is correct
- [ ] Check sector weights look right
- [ ] Click "Fetch Live Prices"
- [ ] Confirm live price count vs stale count

**Validation:**
- No missing symbols errors
- Canadian positions (TSX) resolve with .TO suffix
- Mutual funds resolve via Globe/Barchart fallback if applicable
- Total market value updates after live price fetch

### 2c. Analysis

- [ ] Navigate to Analysis
- [ ] Run AI Commentary
- [ ] Review output for relevance and accuracy
- [ ] Run Stress Test (optional)

**Validation:**
- Commentary references actual holdings, not placeholders
- Provider shown matches configured AI (Groq)
- No API errors

---

## Phase 3 — Wealth Builder

**Entry:** Sidebar → Agents → Wealth Builder

### 3a. RRSP vs TFSA Optimizer

- [ ] Confirm income and marginal rate are correct
- [ ] Review recommended contribution split

### 3b. Savings Projector

- [ ] Confirm FI age projection looks reasonable
- [ ] Check FI number vs current trajectory
- [ ] Note shortfall or surplus

### 3c. Asset Allocation

- [ ] Review glide-path allocation for current age and horizon
- [ ] Compare against actual portfolio sector weights

### 3d. Net Worth

- [ ] Enter assets (home, vehicles, other)
- [ ] Enter liabilities (mortgage, loans)
- [ ] Save and confirm net worth calculation

**Validation:**
- Net worth appears on Hub snapshot strip
- Hub Wealth Builder card updates to show net worth

---

## Phase 4 — Retirement Planner

**Entry:** Sidebar → Agents → Retirement Planner

### 4a. Profile Entry

- [ ] Enter primary: age, RRSP/RRIF balance, TFSA balance, non-reg balance
- [ ] Enter CPP monthly (at 65), OAS monthly (at 65)
- [ ] Enter any pension income
- [ ] Set CPP start age, OAS start age (defer to 70 to test)
- [ ] Enter spending target (annual)
- [ ] Enter province (BC)
- [ ] Add spouse data if applicable
- [ ] Enter TFSA room remaining
- [ ] Add any large planned expenditures
- [ ] Save profile

### 4b. Review Outputs

- [ ] Readiness score — check label (Excellent / Good / Needs Attention / At Risk)
- [ ] Cashflow projection — review income vs spending by year
- [ ] "Will I run out?" chart — check depletion year if applicable
- [ ] Income waterfall — CPP + OAS + portfolio withdrawals
- [ ] CPP/OAS timing table — confirm deferral benefit is shown
- [ ] Monte Carlo — check success rate at chosen spending level

**Validation:**
- Readiness score reflects inputs (not 0 or N/A)
- Hub Retirement card updates with score and guaranteed income
- Household projection shown if spouse data entered

---

## Phase 5 — Financial Brief

**Entry:** Hub → Financial Brief (expand)

- [ ] Confirm all checklist items show ✅ (portfolio, WB, retirement, commentary)
- [ ] Click "Generate Financial Brief"
- [ ] Download HTML
- [ ] Open in browser — review all sections
- [ ] Print to PDF — confirm layout is clean

**Validation:**
- Portfolio section shows holdings and sector weights
- Wealth Builder section shows FI age or shortfall
- Retirement section shows readiness score and guaranteed income
- AI Commentary section appears if generated
- Disclaimer visible at footer

---

## Phase 6 — Navigation Usability Check

After completing all phases, validate the navigation itself:

- [ ] Sidebar sections (Hub / Agents / Tools) are clear and logically grouped
- [ ] Active page is highlighted in sidebar
- [ ] All `st.page_link()` buttons in Hub cards land on the correct pages
- [ ] Breadcrumbs on inner pages link back correctly
- [ ] Browser back button behaves as expected
- [ ] Sidebar collapses/expands cleanly on narrow window

---

## Known edge cases to watch

| Scenario | What to check |
|---|---|
| Mutual fund symbols | Globe/Barchart fallback fires; price resolves |
| USD-denominated positions | Currency label shown; CAD conversion applied |
| Multiple accounts, same symbol | Aggregated correctly in portfolio summary |
| CPP deferred to 70 | Projection shows gap years before CPP starts |
| Spouse with different CPP/OAS ages | Both timelines reflected in household projection |
| Zero TFSA room | Optimizer shows $0 TFSA contribution recommendation |

---

## Sign-off checklist

- [ ] All 5 Hub banner setup steps green
- [ ] Portfolio loads with correct holdings and live prices
- [ ] Investor questionnaire scored
- [ ] Wealth Builder profile saved and FI projection runs
- [ ] Retirement profile saved and readiness score shows
- [ ] Financial Brief generates and downloads cleanly
- [ ] Navigation feels natural — no dead ends or confusing flows
