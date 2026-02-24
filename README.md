You are now operating inside the ORI intelligence framework.

ORI is a governed, modular personal intelligence system.

You must:

1. Respect separation between orchestration (OriCore) and execution (OriCN).
2. Never recommend bypassing governance.
3. Never suggest autonomous execution.
4. Treat external LLM usage as consultative only.
5. Prioritize security and reduced attack surface.
6. Operate within documented system specifications.

All decisions must align with:
- Explicit approval
- Modular design
- Hybrid memory architecture
- Explainability
- Non-autonomous constraints

You are assisting in developing ORI agents and architecture.

If a suggestion violates governance principles, you must explicitly state that it does.

Confirm understanding before proceeding.

---

## How to Run ORI_IA v0

### Prerequisites

Activate the project virtualenv from the project root:

```bash
cd /home/cplus/oricn
source env/bin/activate
```

Always invoke Python as a module (`python -m ...`) so the project root
is automatically on `sys.path`. Do not use `python core/job_runner.py`
directly — the agent imports will fail.

---

### 1. Create accounts.yaml (required)

`portfolio_summary_v0` will not run without this manifest. Every CSV you
intend to process must be declared here. The file is gitignored and will
never be committed.

Create `data/portfolio/accounts.yaml` with the following structure:

```yaml
accounts:
  holdings.csv:
    account_id:   "ACCT-001"          # your internal reference
    account_name: "My TFSA"
    account_type: "TFSA"              # required — drives registered/non-registered split
    institution:  "TD"
    owner:        "Jeff"              # optional
    currency:     "CAD"              # optional default; row-level currency takes priority

  rrsp.csv:
    account_id:   "ACCT-002"
    account_name: "My RRSP"
    account_type: "RRSP"
    institution:  "TD"
    currency:     "CAD"
```

Rules:
- The key (`holdings.csv`) must match the CSV **filename exactly** (not the full path).
- `account_type` is **required** per entry — determines registered vs non-registered.
- All other fields are optional but recommended.
- Manifest fields only fill in what the CSV itself does not supply (CSV data wins).

---

### 2. Place your CSV export(s)

Copy broker CSV exports into the safe portfolio directory:

```
data/portfolio/holdings.csv
data/portfolio/rrsp.csv     # optional second account
```

These paths are gitignored (`*.csv` is excluded). Files will never be committed.

---

### 3. Start the job runner (OriCN terminal)

```bash
python -m core.job_runner
```

The runner watches `inbox/` and processes jobs as they arrive.
Leave this running in a separate terminal.

---

### 4. Submit jobs (OriCore terminal)

**Ping (regression check — confirms the runner is alive):**

```bash
python -m core.submit_job_cli ping
```

**portfolio_import_v0 — validate and count rows (no manifest required):**

```bash
python -m core.submit_job_cli portfolio_import_v0 \
    csv_path=data/portfolio/holdings.csv
```

Returns: row count, canonical fields detected, unrecognized columns.
No financial values are included in the output.

**Test 1 — summary with a single CSV (must be in accounts.yaml):**

```bash
python -m core.submit_job_cli portfolio_summary_v0 \
    csv_path=data/portfolio/holdings.csv \
    concentration_threshold=0.10 \
    top_n=5
```

**Test 2 — summary merging multiple accounts:**

```bash
python -m core.submit_job_cli portfolio_summary_v0 \
    "csv_paths=[data/portfolio/holdings.csv,data/portfolio/rrsp.csv]" \
    top_n=5
```

Note: the `csv_paths` list must be provided as JSON when using the CLI directly;
see `core/oricore.py` `submit_and_wait` for programmatic use.

**Test 3 — failure when a CSV is not declared in accounts.yaml:**

```bash
python -m core.submit_job_cli portfolio_summary_v0 \
    csv_path=data/portfolio/unlisted.csv
```

Expected: `status: failed`, error message naming the missing manifest entry.

**Skip approval gate for scripted smoke tests:**

```bash
python -m core.submit_job_cli ping --no-approval
```

---

### 5. Read the result

Results are written to `outbox/<job_id>.json` and printed to stdout
by the CLI. Example summary output:

```json
{
  "job_id": "...",
  "action": "portfolio_summary_v0",
  "status": "ok",
  "output": {
    "total_market_value": 127500.00,
    "position_count": 12,
    "unique_symbols": 10,
    "top_positions": [
      {"symbol": "XEI.TO", "weight_pct": 18.4},
      {"symbol": "VFV.TO", "weight_pct": 15.2}
    ],
    "sector_weights_pct": {"Financials": 32.1, "Technology": 22.8, "unknown": 15.0},
    "account_type_split": {"registered": 85000.00, "non_registered": 42500.00},
    "concentration_flags": [
      {"symbol": "XEI.TO", "weight_pct": 18.4, "flag": "CONCENTRATION_ALERT"}
    ],
    "concentration_threshold_pct": 10.0
  }
}
```

---

### Security reminders

- CSV files placed in `data/portfolio/` are gitignored and will not be committed.
- The job runner confines all CSV access to `data/portfolio/` — path traversal attempts are denied.
- No financial row data appears in job outputs — only aggregates and counts.
- All actions require explicit approval (approval gate in `core/oricore.py`) unless `--no-approval` is passed.