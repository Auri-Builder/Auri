-- ORI Commercial v0 — Database Schema Placeholder
-- Status: Design only. Not yet applied to any database.
--
-- Target: PostgreSQL 15+  (SQLite-compatible subset for local dev)
-- Naming: snake_case, plural table names, UUID primary keys (stored as TEXT)
--
-- Principles:
--   - Snapshots are append-only (no UPDATE on portfolio_snapshots)
--   - Audit log is append-only (no UPDATE or DELETE on audit_log)
--   - Soft deletes on mutable tables (deleted_at IS NOT NULL)
--   - All monetary values: NUMERIC(18, 4) — switch from REAL when precision matters
--   - All timestamps: TIMESTAMPTZ (UTC)

-- ---------------------------------------------------------------------------
-- clients
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clients (
    client_id       TEXT        PRIMARY KEY,
    name            TEXT        NOT NULL,
    email           TEXT,
    advisor_id      TEXT,
    created_at      DATE,
    deleted_at      TIMESTAMPTZ,
    metadata_json   TEXT        DEFAULT '{}'  -- CRM passthrough fields
);

-- ---------------------------------------------------------------------------
-- accounts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    account_id      TEXT        PRIMARY KEY,
    client_id       TEXT        NOT NULL REFERENCES clients(client_id),
    account_type    TEXT        NOT NULL,  -- AccountType enum value
    institution     TEXT        NOT NULL,
    currency        TEXT        NOT NULL DEFAULT 'CAD',
    is_registered   BOOLEAN     NOT NULL DEFAULT FALSE,
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_accounts_client ON accounts(client_id);

-- ---------------------------------------------------------------------------
-- risk_profiles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_profiles (
    profile_id                  TEXT        PRIMARY KEY,
    client_id                   TEXT        NOT NULL REFERENCES clients(client_id),
    risk_score                  REAL        NOT NULL,
    risk_tolerance              TEXT        NOT NULL,
    primary_goal                TEXT        NOT NULL,
    time_horizon_years          INTEGER,
    max_single_position_pct     REAL        NOT NULL DEFAULT 20.0,
    max_sector_pct              REAL        NOT NULL DEFAULT 40.0,
    max_drawdown_tolerance_pct  REAL,
    excluded_sectors_json       TEXT        DEFAULT '[]',
    completeness_pct            REAL        NOT NULL DEFAULT 0.0,
    scored_at                   DATE,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_risk_profiles_client ON risk_profiles(client_id);

-- ---------------------------------------------------------------------------
-- ips (Investment Policy Statements)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ips (
    ips_id              TEXT        PRIMARY KEY,
    client_id           TEXT        NOT NULL REFERENCES clients(client_id),
    profile_id          TEXT        REFERENCES risk_profiles(profile_id),
    effective_date      DATE        NOT NULL,
    target_return_pct   REAL,
    benchmark           TEXT,
    review_frequency    TEXT        NOT NULL DEFAULT 'annual',
    ai_opt_in           BOOLEAN     NOT NULL DEFAULT FALSE,  -- governed AI consent
    notes               TEXT,
    superseded_at       TIMESTAMPTZ  -- NULL = currently active
);

CREATE INDEX IF NOT EXISTS idx_ips_client ON ips(client_id);

-- ---------------------------------------------------------------------------
-- portfolio_snapshots  (APPEND-ONLY — no UPDATE)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id                 TEXT        PRIMARY KEY,
    client_id                   TEXT        NOT NULL REFERENCES clients(client_id),
    created_at                  TIMESTAMPTZ NOT NULL,
    total_market_value          REAL        NOT NULL,
    total_cost_basis            REAL,
    total_unrealized_gain       REAL,
    total_unrealized_gain_pct   REAL,
    account_count               INTEGER     NOT NULL,
    position_count              INTEGER     NOT NULL,
    registered_value            REAL        NOT NULL DEFAULT 0.0,
    non_registered_value        REAL        NOT NULL DEFAULT 0.0,
    unclassified_value          REAL        NOT NULL DEFAULT 0.0,
    risk_score                  REAL,
    risk_tolerance              TEXT,
    positions_json              TEXT        DEFAULT '[]',  -- aggregates only
    sector_weights_json         TEXT        DEFAULT '{}',
    concentration_flags_json    TEXT        DEFAULT '[]',
    ips_violations_json         TEXT        DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_snapshots_client_time
    ON portfolio_snapshots(client_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- audit_log  (APPEND-ONLY — no UPDATE or DELETE)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    audit_entry_id  TEXT        PRIMARY KEY,
    action_type     TEXT        NOT NULL,  -- e.g. 'llm_call', 'snapshot_write', 'ips_change'
    actor_id        TEXT        NOT NULL,  -- advisor or system user
    client_id       TEXT,                  -- NULL for system-level actions
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    details_json    TEXT        DEFAULT '{}'  -- action-specific fields
    -- Examples for llm_call: provider, model, prompt_hash, prompt_length,
    --   response_length, ips_id (consent reference)
);

-- No foreign keys on audit_log — it must remain insertable even if
-- referenced entities are soft-deleted.
CREATE INDEX IF NOT EXISTS idx_audit_log_client ON audit_log(client_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action  ON audit_log(action_type, timestamp DESC);
