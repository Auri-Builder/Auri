# Auri Deployment Model
Version: 1.0
Status: Strategic

---

## 1. Overview

ORI supports multiple deployment profiles:

- Local-Only Mode
- Hybrid Mode
- Enterprise Mode
- Air-Gapped Mode

---

## 2. Local-Only Mode

Use Case:
- Personal use
- Sensitive environments
- No external LLM augmentation

Characteristics:
- All processing local
- No external API calls
- Memory local
- Execution isolated

---

## 3. Hybrid Mode (Preferred Long-Term Model)

Use Case:
- Advanced reasoning augmentation
- Scenario modeling
- Narrative explanation

Architecture:

Local Secure Plane:
- OriCore
- OriCN
- Agents
- Memory
- Governance engine

Cloud Augmentation Plane:
- External LLM services
- Optional vector indexing

Rules:
- Only sanitized summaries leave local plane
- All outbound calls logged
- No raw data transmission

---

## 4. Enterprise Mode

Use Case:
- Corporate deployments
- Advisor firms
- Regulated environments

Requirements:
- Role-based access control
- Multi-tenant isolation
- Policy enforcement engine
- Data classification tagging
- Encryption at rest
- Encryption in transit
- Audit log export capability

---

## 5. Air-Gapped Mode

Use Case:
- Highly secure environments
- Regulatory isolation
- Defense-level constraints

Characteristics:
- No external LLM
- Optional local LLM
- Full offline operation
- Controlled memory

---

## 6. Future Considerations

- Containerized deployment (Docker)
- Kubernetes orchestration
- On-prem appliance model
- Enterprise licensing model
- Agent marketplace model

---

## 7. Strategic Direction

ORI is designed so that:

- Core governance is deployment-agnostic.
- Agents do not depend on cloud.
- Memory architecture supports partitioning.
- Cloud augmentation is optional, not foundational.