"""
ori_commercial_v0/services/ai_orchestrator.py
──────────────────────────────────────────────
STUB — not yet implemented.

Governed AI orchestration layer for ORI Commercial.

Governance rules (non-negotiable):
1. LLM calls require explicit per-client opt-in (stored in IPS / client record).
2. Only PortfolioSnapshot aggregates are sent to the LLM — NEVER raw holdings,
   account identifiers, or personal data.
3. Every LLM call is logged to the audit trail:
   - client_id, timestamp, provider, model, prompt_length, response_length
   - prompt hash (for replay/verification)
   - opt-in reference (which IPS or consent record authorises this call)
4. Cloud LLM providers require an additional data residency check:
   - Canadian client data must only be sent to providers with Canadian or
     agreed data residency (future: configurable per-client).
5. Local LLM (Ollama) is always permitted — no data leaves the server.
6. No autonomous action proposals — observations and questions only.

Design notes:
- The orchestrator is a thin governance wrapper around LLM adapters.
- It does not implement LLM adapters itself — those live in a shared
  adapters module (to be designed in a future commercial phase).
- Prompt construction enforces the whitelist at build time (not at call time).

IMPORTANT: Do NOT import from agents/, core/, or pages/.
"""

from __future__ import annotations


def generate_portfolio_commentary(
    snapshot,          # PortfolioSnapshot
    client_id: str,
    ips,               # IPS — used to verify opt-in
    provider_config: dict,
    audit_log,         # AuditRepository — logs every call
) -> dict:
    """
    Generate governed LLM commentary for a client's portfolio.

    Parameters
    ----------
    snapshot : PortfolioSnapshot
        Immutable aggregate — the only data sent to the LLM.
    client_id : str
        Used for audit logging and opt-in verification.
    ips : IPS
        Must contain ai_opt_in: True or this call raises PermissionError.
    provider_config : dict
        LLM provider config (provider, model, base_url, api_key_env).
        API keys are NEVER stored here — read from env vars only.
    audit_log : AuditRepository
        Every call is written here before and after the LLM invocation.

    Returns
    -------
    dict:
        commentary (str)   — Markdown-formatted observations + questions
        provider_used (str)
        prompt_length (int)
        audit_entry_id (str)

    Raises
    ------
    PermissionError
        If the client has not opted in to AI commentary in their IPS.
    NotImplementedError
        Until implemented.
    """
    raise NotImplementedError("ai_orchestrator is a stub.")
