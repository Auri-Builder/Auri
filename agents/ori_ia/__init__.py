"""
ORI_IA — Investment Advisor Agent
Version: 0.1.0 (v0, local-only)

Agent manifest (per ORI_PLUGIN_MODEL):
  name:     ORI_IA
  version:  0.1.0
  phase:    v0 — Consolidation + Policy Analysis (local, no network)

  capabilities:
    - read_portfolio_data    (CSV from data/portfolio/ only, path sandboxed)
    - analyze_financials     (local aggregation, no external calls)

  data_classification:
    consumes:  CSV exports from disk (gitignored, never committed)
    produces:  aggregate analytics JSON (no raw row data in output)
    external:  none

  governance:
    - may:    analyze, summarize, flag concentrations, recommend
    - may not: execute trades, access broker APIs, bypass approval gates
"""
