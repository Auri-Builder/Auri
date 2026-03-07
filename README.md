# Auri — Personal Investment Intelligence

A governed, offline-first portfolio analytics system for self-hosted use.
Ingests broker CSV exports, produces structured portfolio analysis, and
generates profile-aware LLM commentary — with no cloud dependency by default.

---

## What it does

- Parses TD WebBroker CSV exports (and similar broker formats) into a canonical schema
- Aggregates holdings across multiple accounts (TFSA, RRSP, CASH, RESP, etc.)
- Computes sector weights, P&L, concentration flags, and account-type splits
- Fetches live prices and dividend income from Yahoo Finance (on demand)
- Generates LLM portfolio commentary via Ollama (local), Anthropic, OpenAI, or xAI
- Maintains an investor risk profile and injects it into commentary prompts
- Saves point-in-time snapshots for portfolio comparison over time
- All via a Streamlit dashboard — no external services required in default mode

---

## Design principles

- **Offline by default** — no network calls unless explicitly requested
- **Governed** — all actions go through an approval gate and job queue
- **No raw data to LLM** — only whitelisted aggregates reach the AI layer
- **Gitignored financials** — CSV files, profile, answers, and account manifests never committed

---

## Prerequisites

- Python 3.12+
- [Ollama](https://ollama.com) (optional — for local LLM commentary)
- A broker that exports CSV holdings (tested with TD WebBroker)

---

## Setup

```bash
git clone https://github.com/your-username/auri.git
cd auri
python3 -m venv env
source env/bin/activate
pip install -r requirements-dev.txt
```

---

## Configuration

### 1. accounts.yaml (required)

Create `data/portfolio/accounts.yaml` to declare your CSV files:

```yaml
accounts:
  holdings.csv:
    account_id:   "ACCT-001"
    account_name: "My TFSA"
    account_type: "TFSA"          # TFSA | RRSP | RRIF | RESP | CASH | USD_CASH
    institution:  "TD"
    currency:     "CAD"
```

This file is gitignored and will never be committed.

### 2. Place your CSV exports

```
data/portfolio/holdings.csv
data/portfolio/rrsp.csv    # additional accounts as needed
```

All `*.csv` files in `data/portfolio/` are gitignored.

### 3. (Optional) LLM commentary

For local Ollama (default — no API key needed):
```bash
ollama pull llama3.2
```

For a cloud provider, create `llm_config.yaml` (gitignored):
```yaml
provider: cloud
cloud:
  provider: anthropic   # anthropic | openai | xai
  model: claude-haiku-4-5-20251001
```

Then export your API key before starting the app:
```bash
export ANTHROPIC_API_KEY=sk-...
```

---

## Running the dashboard

**Dev mode** (no job runner needed) — create `dashboard.yaml` at the repo root:
```yaml
dev_direct_call: true
```

Then start the app:
```bash
source env/bin/activate
python -m streamlit run Home.py
```

Opens at `http://localhost:8501`.

**Governed mode** (default) — run the job runner in a separate terminal:
```bash
python -m core.job_runner
```

Then start the app without `dashboard.yaml`.

---

## Investor profile

The risk-profiling questionnaire is at `data/portfolio/questions.yaml`.
Answer it via the Profile page in the dashboard, or by creating
`data/portfolio/answers.yaml` directly (gitignored).

The profile drives:
- A deterministic risk score (0–100)
- Profile-aware LLM commentary (goals, constraints, retirement context, income coverage)

---

## Security

- CSV files and personal data are confined to `data/portfolio/` and gitignored
- Path traversal outside the project root is denied at the job runner level
- The LLM receives only whitelisted aggregate fields — no account identifiers,
  file paths, or institution names
- See [SECURITY_NOTES.md](SECURITY_NOTES.md) for full hardening notes

---

## Project structure

```
agents/ori_ia/      Analytics, normalization, enrichment, LLM adapter
core/               Job runner, job queue, CLI
data/portfolio/     CSV exports + manifest (gitignored)
data/derived/       Saved snapshots (gitignored)
docs/               Architecture and specification documents
pages/              Streamlit pages (wizard, health, snapshots, profile)
refs/symbols.yaml   Symbol reference data (sector, asset class, Yahoo ticker overrides)
tests/              Pytest test suite
app.py              Streamlit dashboard entry point
```

---

## Running tests

```bash
source env/bin/activate
python -m pytest
```
