# Auri Engineering Standards
Version: 1.0

---

## 1. Code Rules

- No arbitrary command execution
- All system actions routed through ACTION_HANDLERS
- All agents must be stateless except memory modules
- No direct external calls without approval layer

---

## 2. Logging Standards

Every job must log:
- job_id
- action
- timestamp_start
- timestamp_end
- status
- error (if any)

Logs must be append-only.

---

## 3. Agent Rules

Agents:
- Accept structured input
- Produce structured output
- Must be testable independently
- Must not bypass governance layer

---

## 4. Memory Rules

- Global memory stored separately from domain memory
- No direct mutation without consolidation routine
- Memory writes must be logged
- Memory promotion must be explicit

---

## 5. External LLM Rules

- Must pass through approval layer
- Must sanitize data
- Must log request/response metadata
- Must never receive raw credentials