# ORI — Personal vs Commercial Architecture

This document explains the two parallel tracks inside this repository and the
rules that keep them separate.

---

## Why two tracks?

ORI began as a personal finance intelligence tool (one user, local machine,
no network, no customer data).  As the commercial product vision clarified,
it became clear that the two use cases have fundamentally different:

- **Data models** — personal: flat YAML files; commercial: relational DB,
  CRM integration, multi-client isolation
- **Deployment** — personal: developer laptop; commercial: hosted SaaS or
  on-prem with auth, audit, and multi-tenancy
- **Governance** — personal: job-runner allowlist; commercial: full RBAC,
  IPS policy engine, regulatory audit trail
- **LLM posture** — personal: optional Ollama/cloud, one user consents;
  commercial: governed AI orchestrator, per-client opt-in, full audit log

Rather than try to build one framework that satisfies both, we keep a clean
separation from the start.

---

## Track 1 — ORI Personal

### Purpose
Single-user personal intelligence hub for Jeff.  Manages a Canadian equity
and registered-account portfolio.  Offline by default.

### Location in repo
```
agents/ori_ia/          # analytics, risk profiler, LLM adapters
core/                   # job runner (governed action allowlist)
pages/                  # Streamlit dashboard pages
app.py                  # main dashboard entrypoint
data/portfolio/         # GITIGNORED personal data (CSVs, accounts.yaml,
                        #   profile.yaml, answers.yaml)
data/portfolio/questions.yaml   # TRACKED — question template (no PII)
refs/symbols.yaml               # TRACKED — public market enrichment data
```

### Non-negotiables
- No network calls by default.
- All job actions go through the `ACTION_HANDLERS` allowlist in `core/job_runner.py`.
- CSVs, accounts.yaml, profile.yaml, and answers.yaml are **gitignored** — never committed.
- LLM calls are on-demand only, explicitly gated, snapshot-only context.
- Raw financial data never appears in any output or snapshot.
- Derived outputs (snapshots) are aggregates only.

### Modules
| Module | Purpose |
|--------|---------|
| `agents/ori_ia/normalize.py` | CSV ingestion + column mapping |
| `agents/ori_ia/analytics.py` | Portfolio aggregates (market value, P&L, sector weights) |
| `agents/ori_ia/enrich.py` | Sector/asset class enrichment from refs/symbols.yaml |
| `agents/ori_ia/risk_profile.py` | Deterministic risk scorer (questions + answers → score) |
| `agents/ori_ia/commentary.py` | LLM prompt builder with strict data whitelist |
| `agents/ori_ia/llm_adapter.py` | Local (Ollama) and cloud (Anthropic/OpenAI/xAI) adapters |
| `core/job_runner.py` | Action allowlist, all governed handlers |
| `pages/profile.py` | Investor profile dashboard (risk score, completeness, constraints) |
| `pages/health.py` | CSV file health checks |
| `pages/snapshots.py` | Snapshot compare |
| `pages/wizard.py` | CSV upload wizard |

### Planned future agents (ORI Personal)
- **RetirementAgent** — income projection over time, wealth transfer modelling,
  OAS/CPP optimisation, tax-minimisation scenarios.  Separate from portfolio
  analytics; works from a `retirement_plan.yaml` (gitignored).
- **ChatPanel** — multi-turn conversational interface backed by profile +
  snapshot context.  Builds on the existing commentary/LLM adapter layer.

---

## Track 2 — ORI Commercial v0

### Purpose
Clean-room foundation for a multi-client wealth management intelligence
platform.  Nothing from Track 1 is imported or referenced here.

### Location in repo
```
ori_commercial_v0/      # self-contained; no cross-imports from agents/ or core/
```

### Architecture principles
```
Connectors → Canonical Domain → Snapshot → Engines → Governed AI → Audit
```

Each layer has a single responsibility and communicates only through
well-typed interfaces:

1. **Connectors** — pull data from external systems (CRM, custodian, docs).
   Translate to canonical domain objects.  No business logic here.
2. **Canonical Domain** — Pydantic v2 dataclasses: Client, Account, Holding,
   RiskProfile, IPS, Snapshot.  Single source of truth for all downstream code.
3. **Snapshot** — immutable, timestamped aggregate.  Analytics and AI engines
   only ever see snapshots, never live data.
4. **Engines** — analytics_engine, risk_engine.  Pure functions over snapshots.
5. **Governed AI** — ai_orchestrator.  Per-client opt-in.  Full audit log.
   Never calls LLM with raw data; only snapshot aggregates.
6. **Audit** — every action, every LLM call, every snapshot write is logged
   with actor, timestamp, and input/output hash.

### Why Pydantic v2?
- Built-in validation (critical for multi-source custodian data)
- JSON schema export (API contracts, Salesforce field mapping)
- Native serialisation/deserialisation for snapshot storage
- Compatible with FastAPI if a web layer is added later

### What is NOT in v0
- No authentication or multi-tenancy (designed for, not implemented)
- No Salesforce or custodian connector implementations (interfaces only)
- No wiring to ORI Personal code

---

## Cross-track rules

| Rule | Reason |
|------|--------|
| `ori_commercial_v0/` must not import from `agents/`, `core/`, or `pages/` | Keeps commercial foundation clean; avoids personal-use assumptions |
| `agents/`, `core/`, `pages/` must not import from `ori_commercial_v0/` | ORI Personal must remain runnable without Pydantic or commercial deps |
| No shared config files | Each track has its own YAML schema and defaults |
| Tests are separate | `tests/` covers ORI Personal; `ori_commercial_v0/tests/` (future) covers commercial |
| Dependency divergence is intentional | Personal: stdlib + pandas + streamlit + yaml; Commercial: adds pydantic, sqlalchemy (future), potentially FastAPI |
