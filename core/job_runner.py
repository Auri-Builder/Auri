import time
import json
import uuid
import yaml
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# ORI_IA agent imports
#
# Imported at module level so any missing dependency surfaces at startup
# rather than at job execution time.
#
# These imports rely on PROJECT_ROOT being on sys.path, which is automatic
# when the runner is invoked as:  python -m core.job_runner
# ---------------------------------------------------------------------------
from agents.ori_ia.normalize import normalize_csv
from agents.ori_ia.analytics import build_summary
from agents.ori_ia.enrich import load_symbol_ref, enrich_rows


INBOX = Path(__file__).resolve().parent.parent / "inbox"
PROCESSING = Path(__file__).resolve().parent.parent / "processing"
OUTBOX = Path(__file__).resolve().parent.parent / "outbox"
FAILED = Path(__file__).resolve().parent.parent / "failed"
LOGS = Path(__file__).resolve().parent.parent / "logs"
LOGS.mkdir(exist_ok=True)

JOBS_LOG = LOGS / "jobs.jsonl"

PROJECT_ROOT = Path("/home/cplus/oricn").resolve()

# ---------------------------------------------------------------------------
# SAFE_PORTFOLIO_DIR
#
# SECURITY PRINCIPLE: Double sandbox for financial data.
#
# Portfolio CSVs must reside inside this directory — tighter than the
# general PROJECT_ROOT sandbox used by list_dir and similar actions.
# This prevents a job from reading arbitrary files even within the project.
# ---------------------------------------------------------------------------
SAFE_PORTFOLIO_DIR = (PROJECT_ROOT / "data" / "portfolio").resolve()

# Canonical location of the accounts manifest (already inside SAFE_PORTFOLIO_DIR).
ACCOUNTS_MANIFEST_PATH = SAFE_PORTFOLIO_DIR / "accounts.yaml"

# Symbol reference file — public market data, tracked in git, optional.
# Stored under refs/ (not data/) so it is not caught by the data/* gitignore rule.
# Enriches sector/asset_class fields that broker CSV exports typically omit.
SYMBOL_REF_PATH = (PROJECT_ROOT / "refs" / "symbols.yaml").resolve()

# ---------------------------------------------------------------------------
# handle_list_dir
#
# SECURITY PRINCIPLE:
# Workspace sandbox enforcement.
#
# - Path must be a string
# - Path is resolved relative to PROJECT_ROOT
# - Directory traversal outside PROJECT_ROOT is denied
#
# Prevents access to arbitrary filesystem locations.
# ---------------------------------------------------------------------------
def handle_list_dir(params):
    path = params.get("path")

    if not isinstance(path, str):
        return {"error": "Invalid path type"}

    target = (PROJECT_ROOT / path).resolve()

    if not str(target).startswith(str(PROJECT_ROOT)):
        return {"error": "Path outside allowed root"}

    if not target.exists():
        return {"error": "Path does not exist"}

    return {
        "path": str(target),
        "entries": [p.name for p in target.iterdir()]
    }

def handle_ping(params):
    return {"message": "pong"}


# ---------------------------------------------------------------------------
# _resolve_one_csv / _resolve_csv_path / _resolve_csv_paths
#
# SECURITY PRINCIPLE: Symlink-safe double sandbox.
#
# All CSV access for ORI_IA actions must pass through these helpers.
#
# _resolve_one_csv:   core validation on a single raw path string.
# _resolve_csv_path:  wraps _resolve_one_csv for single-file params dicts
#                     (used by portfolio_import_v0).
# _resolve_csv_paths: wraps _resolve_one_csv for csv_path / csv_paths params
#                     (used by portfolio_summary_v0).
#
# Validation steps (all three share via _resolve_one_csv):
#   1. Input must be a non-empty string.
#   2. Resolve symlinks before containment check — prevents a symlink that
#      points outside SAFE_PORTFOLIO_DIR from bypassing the sandbox.
#   3. is_relative_to() for containment — immune to prefix string collisions
#      (e.g. "/data/portfolio2" would fool a startswith check).
#   4. File must exist and end with .csv.
# ---------------------------------------------------------------------------

def _resolve_one_csv(raw: str) -> "Path | dict":
    """Resolve and sandbox a single raw CSV path string."""
    if not isinstance(raw, str) or not raw.strip():
        return {"error": f"CSV path must be a non-empty string, got: {raw!r}"}

    resolved = (PROJECT_ROOT / raw.strip()).resolve()

    if not resolved.is_relative_to(SAFE_PORTFOLIO_DIR):
        return {"error": f"CSV path is outside the allowed portfolio directory: {raw!r}"}

    if not resolved.exists():
        return {"error": f"CSV file not found: {resolved.name}"}

    if resolved.suffix.lower() != ".csv":
        return {"error": f"Only .csv files are permitted, got: {resolved.name}"}

    return resolved


def _resolve_csv_path(params: dict) -> "Path | dict":
    """
    Validate and resolve a 'csv_path' job parameter to a safe, real path.
    Used by portfolio_import_v0 (single-file only).
    """
    raw = params.get("csv_path")
    if not isinstance(raw, str) or not raw.strip():
        return {"error": "csv_path must be a non-empty string"}
    return _resolve_one_csv(raw)



# ---------------------------------------------------------------------------
# _load_accounts_manifest
#
# Reads data/portfolio/accounts.yaml — a required file that maps each CSV
# filename to its account metadata.  The manifest path is already within
# SAFE_PORTFOLIO_DIR; no additional sandbox check is needed.
#
# Uses yaml.safe_load exclusively — this prevents execution of arbitrary
# Python tags that full yaml.load would allow.
# ---------------------------------------------------------------------------

def _load_accounts_manifest() -> "dict | dict":
    """
    Load and parse data/portfolio/accounts.yaml.

    Returns:
        The 'accounts' mapping {csv_filename: metadata_dict} on success.
        {"error": str} if the file is missing, unparseable, or malformed.
    """
    if not ACCOUNTS_MANIFEST_PATH.exists():
        return {
            "error": (
                "accounts.yaml not found in data/portfolio/ — "
                "create it before running portfolio_summary_v0 (see README for format)"
            )
        }

    try:
        with ACCOUNTS_MANIFEST_PATH.open("r", encoding="utf-8") as fh:
            manifest = yaml.safe_load(fh)  # safe_load: no arbitrary tag execution
    except yaml.YAMLError as exc:
        return {"error": f"accounts.yaml parse error: {exc}"}

    if not isinstance(manifest, dict) or "accounts" not in manifest:
        return {"error": "accounts.yaml must have a top-level 'accounts' key"}

    accounts = manifest["accounts"]
    if not isinstance(accounts, dict):
        return {"error": "accounts.yaml 'accounts' must be a filename → metadata mapping"}

    return accounts


# ---------------------------------------------------------------------------
# handle_portfolio_import_v0
#
# SECURITY PRINCIPLE: Minimum necessary output.
#
# Reads and normalizes the CSV but returns ONLY metadata — row count,
# which canonical fields were detected, and which columns were unrecognized.
# No raw financial data (prices, values, account numbers) appears in the
# output. The caller can verify the CSV parsed successfully before running
# a summary job.
# ---------------------------------------------------------------------------
def handle_portfolio_import_v0(params: dict) -> dict:
    """
    Validate and parse a portfolio CSV.

    Required param:
        csv_path (str): path relative to PROJECT_ROOT, must be inside
                        data/portfolio/ and end with .csv

    Returns (on success):
        {
            "row_count":              int,
            "canonical_fields_found": [str, ...],   # mapped canonical fields
            "unmapped_columns":       [str, ...],   # dropped CSV columns
        }
    """
    path_or_err = _resolve_csv_path(params)
    if isinstance(path_or_err, dict):
        return path_or_err  # propagates the {"error": ...} dict

    csv_path = path_or_err

    try:
        rows, detected_fields, unmapped_columns = normalize_csv(csv_path)
    except (ValueError, OSError) as exc:
        return {"error": f"CSV parse failed: {exc}"}

    # Return metadata only — no row contents, no financial values.
    return {
        "row_count": len(rows),
        "canonical_fields_found": sorted(detected_fields),
        "unmapped_columns": unmapped_columns,
    }


# ---------------------------------------------------------------------------
# handle_portfolio_summary_v0
#
# SECURITY PRINCIPLE: Aggregates only. Manifest-gated file access.
#
# All CSVs must be declared in data/portfolio/accounts.yaml before they can
# be processed. This prevents arbitrary CSV reads even within the sandbox —
# the manifest is the explicit allowlist for financial data files.
#
# Manifest metadata (account_type, institution, currency) is injected into
# rows where the CSV itself did not supply those fields. CSV data takes
# priority; the manifest fills gaps only.
#
# Output contains computed aggregates only — no row-level financial data.
# ---------------------------------------------------------------------------
def handle_portfolio_summary_v0(params: dict) -> dict:
    """
    Produce a full portfolio analytics summary from one or more CSVs.

    Optional params (selection — omit all to auto-load every manifest entry):
        csv_path  (str):              single CSV relative to PROJECT_ROOT
        csv_paths (str | list[str]):  one or more CSVs; rows are merged before analysis
                                      a bare string is treated as a one-element list

    All CSVs must be declared in data/portfolio/accounts.yaml (required manifest).
    If accounts.yaml is missing, empty, or a CSV is not listed in it, the job fails.

    Optional params:
        concentration_threshold (float): flag positions above this fraction.
                                         Default: 0.10 (10%)
        top_n (int): number of top positions to include. Default: 5

    Returns:
        {
            "total_market_value":          float,
            "position_count":              int,
            "unique_symbols":              int,
            "top_positions":               [{symbol, weight_pct}, ...],
            "sector_weights_pct":          {sector: pct, ...},
            "account_type_split":          {bucket: market_value, ...},
            "concentration_flags":         [{symbol, weight_pct, flag}, ...],
            "concentration_threshold_pct": float,
            "accounts_loaded":             [{file, account_type, institution}, ...],
        }
    """
    # --- 1. Load accounts manifest (required in all cases) ---
    # Must happen before path resolution so the manifest can supply the file
    # list when the caller omits csv_path / csv_paths entirely.
    accounts_or_err = _load_accounts_manifest()
    if isinstance(accounts_or_err, dict) and "error" in accounts_or_err:
        return accounts_or_err
    accounts: dict = accounts_or_err

    if not accounts:
        return {"error": "accounts.yaml has no entries — add at least one CSV entry"}

    # --- 2. Build path → metadata map from manifest ---
    # Each entry may supply an explicit 'csv_path' field; otherwise the path is
    # derived as data/portfolio/{key}. This supports both current format
    # (key = filename) and future format (key = logical name + explicit csv_path).
    path_meta: dict = {}
    for acct_key, meta in accounts.items():
        if not isinstance(meta, dict):
            return {"error": f"Manifest entry '{acct_key}' must be a key/value mapping"}
        raw_path = meta.get("csv_path") or f"data/portfolio/{acct_key}"
        resolved = _resolve_one_csv(str(raw_path))
        if isinstance(resolved, dict):
            return {"error": f"Account '{acct_key}': {resolved['error']}"}
        path_meta[resolved] = meta

    # --- 3. Resolve the caller's CSV selection, or default to all manifest entries ---
    single = params.get("csv_path")
    multiple = params.get("csv_paths")

    if single is not None and multiple is not None:
        return {"error": "Provide either csv_path or csv_paths, not both"}

    if single is None and multiple is None:
        # Auto-load: process every CSV registered in the manifest.
        csv_paths = list(path_meta.keys())

    elif single is not None:
        resolved = _resolve_one_csv(single)
        if isinstance(resolved, dict):
            return resolved
        if resolved not in path_meta:
            return {"error": f"'{resolved.name}' is not declared in accounts.yaml"}
        csv_paths = [resolved]

    else:
        # csv_paths: accept a single string or a list of strings.
        if isinstance(multiple, str):
            multiple = [multiple]
        if not isinstance(multiple, list) or len(multiple) == 0:
            return {"error": "csv_paths must be a non-empty list or string"}
        csv_paths = []
        for raw in multiple:
            resolved = _resolve_one_csv(raw)
            if isinstance(resolved, dict):
                return resolved
            if resolved not in path_meta:
                return {"error": f"'{resolved.name}' is not declared in accounts.yaml"}
            csv_paths.append(resolved)

    # --- 4. Validate optional analytics params ---
    raw_threshold = params.get("concentration_threshold", 0.10)
    if not isinstance(raw_threshold, (int, float)):
        return {"error": "concentration_threshold must be a number"}
    concentration_threshold = float(raw_threshold)
    if not (0.0 < concentration_threshold < 1.0):
        return {"error": "concentration_threshold must be between 0 and 1 exclusive"}

    raw_top_n = params.get("top_n", 5)
    if not isinstance(raw_top_n, int):
        return {"error": "top_n must be an integer"}
    if raw_top_n < 1:
        return {"error": "top_n must be at least 1"}

    # --- 5. Normalize each CSV, inject manifest metadata, accumulate rows ---
    all_rows: list[dict] = []
    accounts_loaded: list[dict] = []

    for csv_path in csv_paths:
        filename = csv_path.name
        meta = path_meta[csv_path]  # guaranteed present — built from same manifest

        # account_type is required in the manifest so the registered/non-registered
        # split is always deterministic, even when the CSV omits it.
        if not meta.get("account_type"):
            return {"error": f"Manifest entry for '{filename}' is missing required field: account_type"}

        try:
            rows, _, _ = normalize_csv(csv_path)
        except (ValueError, OSError) as exc:
            return {"error": f"CSV parse failed for '{filename}': {exc}"}

        # Inject manifest fields into rows where the CSV left them blank.
        # CSV-supplied values always take priority (we only fill None fields).
        for row in rows:
            for field in ("account_id", "account_type", "institution", "currency"):
                if row.get(field) is None and meta.get(field):
                    row[field] = str(meta[field]).strip() or None

        all_rows.extend(rows)

        # Record which accounts were loaded (metadata only, no financial values).
        accounts_loaded.append({
            "file":         filename,
            "account_type": meta.get("account_type"),
            "institution":  meta.get("institution"),
        })

    # --- 5b. Enrich sector/asset_class from local symbol reference ---
    # Optional: if symbols.yaml is absent, enrichment is skipped gracefully.
    # CSV-supplied and manifest-injected values already take priority (only fills None).
    try:
        symbol_ref = load_symbol_ref(SYMBOL_REF_PATH)
    except ValueError as exc:
        return {"error": f"symbols.yaml parse error: {exc}"}
    enrich_rows(all_rows, symbol_ref)

    # --- 6. Run analytics on the merged row set ---
    summary = build_summary(
        all_rows,
        concentration_threshold=concentration_threshold,
        top_n=raw_top_n,
    )
    summary["accounts_loaded"] = accounts_loaded
    return summary


# ---------------------------------------------------------------------------
# ACTION REGISTRY
#
# SECURITY PRINCIPLE:
# Default deny.
#
# Only explicitly registered actions may execute.
# This prevents arbitrary or injected job actions from running.
#
# If an action is not listed here, it will be marked as "denied".
# ---------------------------------------------------------------------------
ACTION_HANDLERS = {
    "ping":                    handle_ping,
    "list_dir":                handle_list_dir,
    "portfolio_import_v0":     handle_portfolio_import_v0,
    "portfolio_summary_v0":    handle_portfolio_summary_v0,
}


def log_job(record: dict):
    with open(JOBS_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")


def now_str():
    return datetime.now().isoformat(timespec="seconds")

# ---------------------------------------------------------------------------
# run_job
#
# SECURITY PRINCIPLE:
# Controlled execution engine.
#
# Flow:
# 1. Extract action and params
# 2. Validate params type
# 3. Lookup handler via ACTION_HANDLERS (allowlist)
# 4. Deny if action not allowed
# 5. Execute handler
#
# No dynamic command execution.
# No shell access.
# No runtime expansion of capabilities.
#
# This function is the enforcement boundary between
# job submission and system execution.
# ---------------------------------------------------------------------------
def run_job(job: dict) -> dict:
    """
    For now, our "job engine" supports a tiny set of actions.
    We'll expand this safely over time.
    """
    action = job.get("action")
    result = {
        "job_id": job.get("job_id"),
        "action": action,
        "status": "ok",
        "timestamp_start": job.get("timestamp_start"),
        "timestamp_end": None,
        "output": None,
        "error": None,
    }
    params = job.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        result["status"] = "failed"
        result["error"] = "params must be a dict"
        result["timestamp_end"] = now_str()
        return result

    handler = ACTION_HANDLERS.get(action)
    if handler is None:
        result["status"] = "denied"
        result["error"] = f"Action not allowed: {action}"
        result["timestamp_end"] = now_str()
        return result

    output = handler(params)
    if isinstance(output, dict) and output.get("error"):
        result["status"] = "failed"
        result["error"] = output["error"]
        result["timestamp_end"] = now_str()
        return result

    result["output"] = output
    result["timestamp_end"] = now_str()
    return result


def claim_one_job():
    job_files = sorted(INBOX.glob("*.json"))
    if not job_files:
        return None

    job_file = job_files[0]
    claimed = PROCESSING / job_file.name
    job_file.rename(claimed)  # atomic-ish move on same filesystem
    return claimed

def main():
    print("Ori Job Runner started. Watching inbox...")
    while True:
        job_path = claim_one_job()
        if not job_path:
            time.sleep(2)
            continue

        job = None
        try:
            raw = job_path.read_text()
            job = json.loads(raw)
            job["timestamp_start"] = now_str()

            log_job({
                "job_id": job.get("job_id"),
                "action": job.get("action"),
                "status": "processing",
                "timestamp": job["timestamp_start"],
                "file": job_path.name,
            })

            result = run_job(job)

            out_file = OUTBOX / job_path.name
            out_file.write_text(json.dumps(result, indent=2))

            log_job({
                "job_id": result["job_id"],
                "action": result["action"],
                "status": result["status"],
                "timestamp": result["timestamp_end"],
                "out_file": out_file.name,
            })

            print(f"Job complete: {result['job_id']} ({result['status']})")

        except Exception as e:
            # If JSON parsing fails, job might be None; capture raw error safely
            fail_payload = {
                "error": str(e),
                "file": job_path.name,
                "job": job,
            }
            fail_file = FAILED / job_path.name
            fail_file.write_text(json.dumps(fail_payload, indent=2))

            log_job({
                "job_id": (job.get("job_id") if isinstance(job, dict) else None),
                "action": (job.get("action") if isinstance(job, dict) else None),
                "status": "failed_exception",
                "timestamp": now_str(),
                "error": str(e),
            })

            print(f"Job failed with exception: {e}")

        finally:
            # Always remove the processing file once handled
            job_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()