# Auri Security Notes

## 2026-02-22 — Governance Hardening Phase 1

### Changes Implemented

1. **Action Allowlist**
   - Replaced manual `if action == ...` branching with `ACTION_HANDLERS` registry.
   - Default behavior is now **deny** for unknown actions.
   - Reduces attack surface by preventing arbitrary action execution.

2. **Typed Parameter Enforcement**
   - Enforced that `params` must be a dictionary.
   - Prevents malformed or malicious JSON structures from being processed.

3. **Path Sandboxing**
   - All file operations are restricted to `PROJECT_ROOT`.
   - Prevents directory traversal (e.g., `../../etc/passwd`).

4. **Queue Directory Permissions**
   - Set `700` permissions on:
     - inbox
     - processing
     - outbox
     - failed
     - logs
   - Ensures only the owner user can read/write job artifacts.

5. **Execution Separation**
   - Orchestration layer submits jobs only.
   - Execution layer runs jobs.
   - No direct command execution in control plane.

---

## Security Model

Defense in depth:

1. Network boundary (private LAN, SSH keys)
2. OS-level permission enforcement
3. Auri policy enforcement (allowlist + deny-by-default)
4. Workspace sandbox (PROJECT_ROOT constraint)

---

## Future Hardening Ideas

- Job schema validation (UUID + strict contract enforcement)
- Separate Unix users for core vs worker
- Signed job files
- systemd sandboxing for worker
- No shell execution actions unless explicitly designed, gated, and reviewed