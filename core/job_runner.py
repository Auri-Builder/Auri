import time
import json
import uuid
from datetime import datetime
from pathlib import Path


INBOX = Path(__file__).resolve().parent.parent / "inbox"
PROCESSING = Path(__file__).resolve().parent.parent / "processing"
OUTBOX = Path(__file__).resolve().parent.parent / "outbox"
FAILED = Path(__file__).resolve().parent.parent / "failed"
LOGS = Path(__file__).resolve().parent.parent / "logs"
LOGS.mkdir(exist_ok=True)

JOBS_LOG = LOGS / "jobs.jsonl"

PROJECT_ROOT = Path("/home/cplus/oricn").resolve()

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
# ACTION REGISTRY
#
# SECURITY PRINCIPLE:
# Default deny.
#
# Only explicitly registered actions may execute.
# This prevents arbitrary or injected job actions from running.
#
# If an action is not listed here, it will be marked as "denied".
# -------------------------------------------------------------------------
ACTION_HANDLERS = {
    "ping": handle_ping,
    "list_dir": handle_list_dir,
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