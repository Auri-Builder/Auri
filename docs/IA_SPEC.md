# IA – Investment Advisor Agent
Version: 1.0

---

## 1. Scope

ORI_IA consolidates financial documents and produces structured portfolio analysis.

It does NOT:
- Execute trades
- Access brokerage APIs
- Move funds

---

## 2. Functional Phases

### Phase 1 – Consolidation
- Parse CSV exports
- Normalize schema
- Separate:
    - Registered
    - Non-registered
- Produce unified portfolio view

### Phase 2 – Policy Analysis
- Position concentration checks
- Sector exposure analysis
- Asset class distribution
- Risk flagging

### Phase 3 – External LLM Augmentation
- Narrative explanation
- Strategy comparison
- Scenario modeling

External LLM is advisory only.

---

## 3. Canonical Schema

All inputs normalize to:

- account_id
- account_type
- institution
- symbol
- security_name
- asset_class
- sector
- quantity
- price
- market_value
- cost_basis
- unrealized_gain
- unrealized_gain_percent
- currency

---

## 4. Memory Integration

ORI_IA retrieves:

- Global investment doctrine
- Paul’s advisory principles
- Diversification standards
- Risk tolerance rules
- Behavioral mindset overlays

Memory is consulted before external LLM usage.

---

## 5. Governance Constraints

ORI_IA may:
- Analyze
- Recommend
- Simulate

ORI_IA may NOT:
- Execute financial transactions
- Override governance
- Access external APIs without approval