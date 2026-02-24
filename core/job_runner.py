import time
import json
import uuid
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
# _resolve_csv_path
#
# SECURITY PRINCIPLE: Symlink-safe double sandbox.
#
# All CSV access for ORI_IA actions must pass through this helper.
#
# Steps:
#   1. Validate csv_path param is a non-empty string.
#   2. Resolve symlinks (prevents symlink traversal to locations outside the
#      sandbox — Path.resolve() follows symlinks before comparison).
#   3. Confirm the resolved path is inside SAFE_PORTFOLIO_DIR
#      (is_relative_to is the correct containment check; startswith on
#      strings is vulnerable to prefix collisions like "/data/portfolio2").
#   4. Confirm the resolved path exists and ends with .csv.
#
# Returns the resolved Path on success, or an error dict on any violation.
# ---------------------------------------------------------------------------
def _resolve_csv_path(params: dict) -> "Path | dict":
    """
    Validate and resolve a 'csv_path' job parameter to a safe, real path.

    Args:
        params: the job params dict (already confirmed to be a dict by run_job)

    Returns:
        Resolved pathlib.Path on success.
        {"error": str} on any validation failure.
    """
    csv_path_raw = params.get("csv_path")

    if not isinstance(csv_path_raw, str) or not csv_path_raw.strip():
        return {"error": "csv_path must be a non-empty string"}

    # Resolve symlinks so that a symlink pointing outside SAFE_PORTFOLIO_DIR
    # cannot be used to bypass the sandbox.
    resolved = (PROJECT_ROOT / csv_path_raw.strip()).resolve()

    # is_relative_to: True only if resolved is SAFE_PORTFOLIO_DIR or a
    # descendant of it — not susceptible to prefix string collisions.
    if not resolved.is_relative_to(SAFE_PORTFOLIO_DIR):
        return {"error": "csv_path is outside the allowed portfolio directory"}

    if not resolved.exists():
        return {"error": f"CSV file not found: {resolved.name}"}

    if resolved.suffix.lower() != ".csv":
        return {"error": "Only .csv files are permitted"}

    return resolved


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
# SECURITY PRINCIPLE: Aggregates only.
#
# Normalizes the CSV internally (same sandbox as import) and runs all
# analytics. The output contains only computed aggregates — totals,
# percentages, flags — not the underlying row-level financial data.
# ---------------------------------------------------------------------------
def handle_portfolio_summary_v0(params: dict) -> dict:
    """
    Produce a full portfolio analytics summary from a CSV.

    Required param:
        csv_path (str): path relative to PROJECT_ROOT, must be inside
                        data/portfolio/ and end with .csv

    Optional params:
        concentration_threshold (float): flag positions above this fraction
                                         of total portfolio. Default: 0.10 (10%)
        top_n (int):  number of top positions to include. Default: 5
        account_type (str): account type override for rows that have no
                            account_type column (e.g. "RRSP", "TFSA")

    Returns:
        {
            "total_market_value":        float,
            "position_count":            int,
            "unique_symbols":            int,
            "top_positions":             [{symbol, weight_pct}, ...],
            "sector_weights_pct":        {sector: pct, ...},
            "account_type_split":        {bucket: market_value, ...},
            "concentration_flags":       [{symbol, weight_pct, flag}, ...],
            "concentration_threshold_pct": float,
        }
    """
    path_or_err = _resolve_csv_path(params)
    if isinstance(path_or_err, dict):
        return path_or_err

    csv_path = path_or_err

    # Optional params — validate types and apply defaults
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

    account_type_override = params.get("account_type")
    if account_type_override is not None and not isinstance(account_type_override, str):
        return {"error": "account_type must be a string"}

    try:
        rows, _, _ = normalize_csv(csv_path)
    except (ValueError, OSError) as exc:
        return {"error": f"CSV parse failed: {exc}"}

    return build_summary(
        rows,
        concentration_threshold=concentration_threshold,
        top_n=raw_top_n,
        account_type_override=account_type_override,
    )


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