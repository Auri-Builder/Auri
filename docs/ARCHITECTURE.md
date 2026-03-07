# Auri Architecture
Version: 1.0

---

User
  ↓
OriCore (Control Plane)
  ↓
JSON Job Queue
  ↓
OriCN (Execution Plane)
  ↓
Agent Layer
  ↓
Memory System
  ↓
External LLM (Optional + Governed)

---

## Control Plane

Responsible for:
- Approval gating
- Job submission
- Monitoring
- Agent routing

No direct execution allowed.

---

## Execution Plane

Responsible for:
- Inbox → Processing → Outbox
- ACTION_HANDLERS whitelist
- Path confinement
- Audit logging

---

## Agent Layer

Each agent:
- Accepts structured input
- Produces structured output
- Cannot execute system commands
- Cannot bypass governance

Examples:
- ORI_IA
- ORI_SW
- ORI_SYS

---

## Memory Architecture (Hybrid Model)

### Global Memory
- Governance principles
- Risk doctrine
- Explainability requirements
- Security philosophy

### Domain Memory
- Agent-specific knowledge
- Advisor principles
- Creative frameworks
- Domain heuristics

### Short-Term Memory
- Recent job outputs
- Observations
- Session context

### Consolidation Layer
- Extract durable lessons
- Remove redundancy
- Validate against governance
- Promote to long-term memory

---

## External LLM Policy

External LLM:
- Is consultative
- Never authoritative
- Never directly connected to execution
- Must be explicitly approved
- Must be logged

No autonomous retraining allowed.