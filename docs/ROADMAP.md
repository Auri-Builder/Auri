# Auri Roadmap

---

## Auri Personal

### Completed
- v0   — normalize + analytics + governed job actions
- v0.1 — symbol enrichment (sector/asset_class from refs/symbols.yaml)
- Phase A — Streamlit dashboard (portfolio_summary_v0 consumer)
- Phase B — CSV upload wizard (pages/wizard.py)
- Phase C — Health checks, snapshots/compare, wizard UX polish
- D2a  — Cost basis duplicate-mapping fix (TD WebBroker "Average Cost" vs "Book Cost")
- D2b  — Cost basis aggregates (per-symbol + portfolio-level P&L)
- D2c  — UI polish: conditional formatting, P&L summary strip, sort
- D3   — Governed LLM commentary layer (Ollama / Anthropic / OpenAI / xAI)
- P1   — Investor profile: profile.yaml, questions.yaml, answers.yaml,
          deterministic risk scorer, portfolio_profile_v0 action, pages/profile.py

### Next — Auri Personal
- P2   — Profile → Commentary integration
          Inject risk score and investor objectives into LLM commentary prompt
          so the voice-of-reason output is profile-aware.
- P3   — Chat panel (multi-turn)
          st.chat_input + conversation history in session state.
          Context: profile + latest snapshot.
- P4   — RetirementAgent (separate agent, separate YAML)
          Income projection, OAS/CPP optimisation, wealth transfer modelling,
          tax-minimisation scenarios.
- v0.2 — Sector/region schema split
          refs/symbols.yaml taxonomy inconsistency: separate `sector` (GICS)
          from `region` (Canada/US/Global).

### Known design debt
- refs/symbols.yaml mixes GICS sectors with geography labels.
  v0.2 will split into `sector` and `region` fields.

---

## Auri Commercial

### Parked — v0 skeleton (in repo, not wired)
- ori_commercial_v0/ foundation:
  - Canonical domain (Pydantic v2): Client, Account, Holding, RiskProfile, IPS, Snapshot
  - Connector interfaces: CRMConnector, CustodianConnector, DocumentConnector
  - Service stubs: snapshot_builder, analytics_engine, risk_engine, ai_orchestrator
  - Storage: db_schema.sql placeholder + repository interfaces

### Future commercial phases (design sessions TBD)
- C1   — Salesforce CRM connector implementation
- C2   — Custodian connector (TD / DTCC / CSV ingestion at scale)
- C3   — Multi-client analytics engine
- C4   — IPS policy engine (Investment Policy Statement compliance checks)
- C5   — Governed AI orchestrator (per-client opt-in, full audit log)
- C6   — Web layer (FastAPI or similar), auth, multi-tenancy
