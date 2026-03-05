# ORI Commercial v0 — Foundation Skeleton

**Status: Parked / design-only.** No wiring to ORI Personal code.

This directory contains the clean-room architecture foundation for the
multi-client commercial product.  Nothing here imports from `agents/`,
`core/`, or `pages/`.

---

## Architecture

```
External Systems
      │
      ▼
┌─────────────┐
│  Connectors │  CRM, Custodian, Documents — translate external → domain
└──────┬──────┘
       │ domain objects (Pydantic v2)
       ▼
┌─────────────┐
│   Domain    │  Client, Account, Holding, RiskProfile, IPS, Snapshot
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ Snapshot Builder│  Immutable, timestamped aggregate of a client's portfolio
└──────┬──────────┘
       │ Snapshot (read-only)
       ┌──────────┬─────────────┐
       ▼          ▼             ▼
┌────────────┐ ┌──────────┐ ┌──────────────┐
│ Analytics  │ │  Risk    │ │ AI           │
│ Engine     │ │ Engine   │ │ Orchestrator │
└────────────┘ └──────────┘ └──────┬───────┘
                                   │ governed, per-client opt-in
                                   ▼
                             ┌──────────┐
                             │  Audit   │  every action logged
                             └──────────┘
```

### Layers

| Layer | Responsibility |
|-------|---------------|
| **Connectors** | Pull from external systems. No business logic. Translate to domain objects. |
| **Domain** | Pydantic v2 typed models. Single source of truth for all downstream code. |
| **Snapshot Builder** | Produces an immutable, timestamped `Snapshot`. Engines/AI only see snapshots. |
| **Analytics Engine** | Pure functions over a `Snapshot`. No I/O. |
| **Risk Engine** | IPS compliance checks, risk score, concentration flags. Pure functions. |
| **AI Orchestrator** | Governed LLM calls. Per-client opt-in. Never receives raw data — snapshots only. Full audit log. |
| **Storage** | Repository pattern. Schema-first. Swap backing store without changing business logic. |

---

## Why Pydantic v2?

- **Validation at the boundary**: Connector output is validated the moment it enters the domain layer.
- **JSON schema export**: Maps directly to Salesforce field definitions, custodian API contracts, and future REST API schemas.
- **Native serialisation**: Snapshots can be stored/loaded as JSON without custom serialisers.
- **FastAPI compatibility**: If a web layer is added, domain models double as API schemas with zero extra code.
- **Strict mode**: `model_config = ConfigDict(strict=True)` prevents silent type coercion — critical for financial data.

---

## Connector interfaces

| Connector | Source |
|-----------|--------|
| `CRMConnector` | Salesforce (or any CRM) — client and account metadata |
| `CustodianConnector` | Custodian data feeds (TD, DTCC, CSV) — holdings and transactions |
| `DocumentConnector` | IPS PDFs, KYC documents — structured extraction |

Interfaces only in v0.  Implementations are separate future phases.

---

## Dependency policy

```
ori_commercial_v0/ → pydantic (required)
ori_commercial_v0/ → MUST NOT import from agents/, core/, pages/
agents/, core/, pages/ → MUST NOT import from ori_commercial_v0/
```

Install commercial deps only when working in this directory:

```bash
pip install pydantic>=2.0
```

---

## Directory layout

```
ori_commercial_v0/
├── README.md                   this file
├── domain/
│   ├── __init__.py
│   └── models.py               Client, Account, Holding, RiskProfile, IPS, Snapshot
├── connectors/
│   ├── __init__.py
│   └── interfaces.py           CRMConnector, CustodianConnector, DocumentConnector (ABC)
├── services/
│   ├── __init__.py
│   ├── snapshot_builder.py     stub
│   ├── analytics_engine.py     stub
│   ├── risk_engine.py          stub
│   └── ai_orchestrator.py      stub (governance notes)
├── storage/
│   ├── __init__.py
│   ├── db_schema.sql           placeholder DDL
│   └── repositories.py         repository interfaces (ABC)
└── tests/
    └── __init__.py
```
