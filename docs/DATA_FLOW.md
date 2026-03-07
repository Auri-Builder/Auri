# Auri Data Flow Specification
Version: 1.0
Status: Foundational

---

## 1. Purpose

This document defines how data enters, moves through, and exits the ORI framework.

The goal is to ensure:

- Explicit data classification
- Controlled movement
- Auditable boundaries
- Hybrid deployment readiness

---

## 2. Data Classification Levels

All data handled by ORI must be classified.

### Level 1 – Public
Examples:
- Documentation
- Non-sensitive logs
- Architecture diagrams

May leave system freely.

---

### Level 2 – Sensitive
Examples:
- Portfolio holdings
- Aggregated analytics
- Consolidated summaries

May leave system ONLY if:
- Explicitly approved
- Sanitized
- Logged

---

### Level 3 – Restricted
Examples:
- Raw financial exports
- Account identifiers
- API credentials
- Personally identifiable information

May NOT leave local execution environment.

---

## 3. Inbound Data Flow

### Portfolio Example

User → OriCore → Job Queue → OriCN → ORI_IA

At no point does raw portfolio data leave the local environment.

---

## 4. Internal Data Movement

Within local secure plane:

1. File ingestion
2. Schema normalization
3. Structured portfolio object
4. Analysis
5. Memory write (if applicable)

All steps logged.

---

## 5. Outbound Data Flow (Hybrid Mode)

When using external LLM augmentation:

1. Agent produces structured summary.
2. Governance engine reviews:
   - Classification level
   - Redaction requirements
3. Only summary-level sanitized data may be sent.
4. Outbound request logged.
5. Response logged.
6. Response validated before use.

Raw data never leaves.

---

## 6. Memory Flow

Short-Term Memory:
- Stores job results
- Session data

Consolidation Layer:
- Extract durable insights
- Validate governance compliance

Long-Term Memory:
- Stores structured principles
- No raw financial documents

---

## 7. Enterprise Data Control

Future commercial version must support:

- Customer-level memory partitioning
- Data residency configuration
- Export capability
- Data deletion workflow
- Immutable audit trail

---

## 8. Non-Negotiable Rule

Restricted data (Level 3) must never:

- Be sent to external LLM
- Be logged externally
- Be embedded in prompts
- Be persisted outside local environment