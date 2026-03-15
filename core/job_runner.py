import re
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
from agents.ori_ia.analytics import build_summary, compute_allocation_deviation, suggest_target_allocation
from agents.ori_ia.enrich import load_symbol_ref, enrich_rows


INBOX = Path(__file__).resolve().parent.parent / "inbox"
PROCESSING = Path(__file__).resolve().parent.parent / "processing"
OUTBOX = Path(__file__).resolve().parent.parent / "outbox"
FAILED = Path(__file__).resolve().parent.parent / "failed"
LOGS = Path(__file__).resolve().parent.parent / "logs"
LOGS.mkdir(exist_ok=True)

JOBS_LOG = LOGS / "jobs.jsonl"

from core._paths import PROJECT_ROOT, get_data_root as _get_data_root, get_data_dir as _get_data_dir  # noqa: F401

# ---------------------------------------------------------------------------
# SAFE_PORTFOLIO_DIR / SAFE_DERIVED_DIR
#
# SECURITY PRINCIPLE: Double sandbox for financial data.
#
# These are functions (not constants) so they always resolve against the
# currently active profile's data directory when called from a handler.
# ---------------------------------------------------------------------------

def _safe_portfolio_dir() -> Path:
    """Return the resolved portfolio sandbox for the active profile."""
    return (_get_data_dir() / "portfolio").resolve()


def _safe_derived_dir() -> Path:
    """Return the resolved derived-outputs sandbox for the active profile."""
    return (_get_data_dir() / "derived").resolve()


# Symbol reference file — public market data, tracked in git, optional.
SYMBOL_REF_PATH = (PROJECT_ROOT / "refs" / "symbols.yaml").resolve()

# LLM provider config (gitignored — API keys must never be stored here).
LLM_CONFIG_PATH = (PROJECT_ROOT / "llm_config.yaml").resolve()

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

APP_VERSION = "1.0.0"

def handle_ping(params):
    return {"message": "pong", "version": APP_VERSION}


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

    safe_dir = _safe_portfolio_dir()
    resolved = (_get_data_root() / raw.strip()).resolve()

    if not resolved.is_relative_to(safe_dir):
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
    _manifest_path = _safe_portfolio_dir() / "accounts.yaml"
    if not _manifest_path.exists():
        return {
            "error": (
                "accounts.yaml not found in data/portfolio/ — "
                "create it before running portfolio_summary_v0 (see README for format)"
            )
        }

    try:
        with _manifest_path.open("r", encoding="utf-8") as fh:
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

    # --- 6b. Owner-split account balances ---
    # Reads accounts.yaml for owner fields and groups balances by (owner, account_type).
    try:
        _amp = _safe_portfolio_dir() / "accounts.yaml"
        _acct_yaml = yaml.safe_load(_amp.read_text()) if _amp.exists() else {}
        _acct_meta = (_acct_yaml or {}).get("accounts", {})
        _id_to_owner = {
            str(m.get("account_id", "")).upper(): m.get("owner", "primary").lower()
            for m in _acct_meta.values()
            if m.get("account_id")
        }
        if _id_to_owner:
            _by_owner: dict[str, dict[str, float]] = {}
            for _row in all_rows:
                _aid   = str(_row.get("account_id") or "").upper()
                _owner = _id_to_owner.get(_aid, "primary")
                _atype = (_row.get("account_type") or "UNCLASSIFIED").upper()
                _mv    = float(_row.get("market_value") or 0.0)
                _by_owner.setdefault(_owner, {})
                _by_owner[_owner][_atype] = _by_owner[_owner].get(_atype, 0.0) + _mv
            summary["account_balance_by_owner"] = {
                o: {k: round(v, 2) for k, v in types.items() if v > 0}
                for o, types in _by_owner.items()
            }
    except Exception:
        pass

    # --- 7. Policy compliance check (optional — requires profile.yaml) ---
    # Loads the investor's stated constraints and flags breaches / warnings.
    # Non-fatal: if profile.yaml is absent, policy_flags is an empty list.
    try:
        from agents.ori_ia.analytics import check_policy  # noqa: PLC0415
        _constraints: dict = {}
        _pp = _safe_portfolio_dir() / "profile.yaml"
        if _pp.exists():
            with _pp.open("r", encoding="utf-8") as fh:
                _prof = yaml.safe_load(fh) or {}
            _constraints = _prof.get("constraints") or {}
        summary["policy_flags"] = check_policy(summary, _constraints)
    except Exception:
        summary["policy_flags"] = []

    return summary


# ---------------------------------------------------------------------------
# _resolve_one_derived_json
#
# SECURITY PRINCIPLE: Snapshot sandbox enforcement.
#
# Mirrors _resolve_one_csv but scoped to data/derived/ and .json files only.
# Prevents compare jobs from reading arbitrary JSON files outside derived/.
# ---------------------------------------------------------------------------

def _resolve_one_derived_json(raw: str) -> "Path | dict":
    """Resolve and sandbox a single snapshot path string."""
    if not isinstance(raw, str) or not raw.strip():
        return {"error": f"Snapshot path must be a non-empty string, got: {raw!r}"}

    safe_dir = _safe_derived_dir()
    resolved = (_get_data_root() / raw.strip()).resolve()

    if not resolved.is_relative_to(safe_dir):
        return {"error": f"Snapshot path is outside data/derived/: {raw!r}"}

    if not resolved.exists():
        return {"error": f"Snapshot file not found: {resolved.name}"}

    if resolved.suffix.lower() != ".json":
        return {"error": f"Only .json snapshot files are permitted, got: {resolved.name}"}

    return resolved


# ---------------------------------------------------------------------------
# handle_portfolio_snapshot_v0
#
# SECURITY PRINCIPLE: Aggregates-only persistence.
#
# Calls the existing summary pipeline and writes a sanitized JSON to
# data/derived/. The output schema is explicitly whitelisted — only
# aggregate fields are written, never row-level holdings data.
# ---------------------------------------------------------------------------

def handle_portfolio_snapshot_v0(params: dict) -> dict:
    """
    Run portfolio_summary_v0 (auto-load all accounts) and persist the
    aggregates-only output to data/derived/<date>-<label>-summary.json.

    Optional params:
        label (str): descriptive tag embedded in the filename.
                     Default: "snapshot". Sanitized to [a-zA-Z0-9_-] only.
        date  (str): YYYY-MM-DD to embed in the filename. Default: today.

    Returns:
        {"snapshot_file": "data/derived/<filename>", "summary": <aggregates>}
    """
    # --- Validate label ---
    raw_label = params.get("label", "snapshot")
    if not isinstance(raw_label, str) or not raw_label.strip():
        return {"error": "label must be a non-empty string"}
    safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_label.strip())

    # --- Validate date ---
    raw_date = params.get("date")
    if raw_date is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    else:
        if not isinstance(raw_date, str):
            return {"error": "date must be a YYYY-MM-DD string"}
        try:
            datetime.strptime(raw_date, "%Y-%m-%d")
        except ValueError:
            return {"error": "date must be in YYYY-MM-DD format"}
        date_str = raw_date

    # --- Run summary pipeline (auto-load all accounts) ---
    summary = handle_portfolio_summary_v0({})
    if "error" in summary:
        return summary

    # --- Build snapshot — whitelist aggregate fields only, no row data ---
    snapshot = {
        "timestamp":                   datetime.now().isoformat(timespec="seconds"),
        "label":                       safe_label,
        "date":                        date_str,
        "total_market_value":          summary.get("total_market_value"),
        "position_count":              summary.get("position_count"),
        "unique_symbols":              summary.get("unique_symbols"),
        "top_positions":               summary.get("top_positions", []),
        "sector_weights_pct":          summary.get("sector_weights_pct", {}),
        "account_type_split":          summary.get("account_type_split", {}),
        "concentration_flags":         summary.get("concentration_flags", []),
        "concentration_threshold_pct": summary.get("concentration_threshold_pct"),
        "accounts_loaded":             summary.get("accounts_loaded", []),
        # Portfolio-level cost-basis aggregates (None when no rows report cost_basis).
        "total_cost_basis":            summary.get("total_cost_basis"),
        "total_unrealized_gain":       summary.get("total_unrealized_gain"),
        "total_unrealized_gain_pct":   summary.get("total_unrealized_gain_pct"),
        # GOVERNANCE: positions_summary is aggregates only (per-symbol totals,
        # registered/non-registered/unclassified sub-totals, account count,
        # cost_basis / unrealized_gain / unrealized_gain_pct per symbol,
        # reconciliation_delta diagnostic field).
        # No row-level holdings data is written to the derived output.
        "positions_summary":                  summary.get("positions_summary", []),
        # Scalar diagnostic: count of positions where rounding folded a delta.
        # 0 in all normal runs; non-zero warrants investigation.
        "positions_with_delta_folded_count":  summary.get("positions_with_delta_folded_count", 0),
    }

    # --- Write to data/derived/ ---
    _derived = _safe_derived_dir()
    _derived.mkdir(parents=True, exist_ok=True)
    filename = f"{date_str}-{safe_label}-summary.json"
    out_path = _derived / filename
    out_path.write_text(json.dumps(snapshot, indent=2))

    return {
        "snapshot_file": f"data/derived/{filename}",
        "summary": snapshot,
    }


# ---------------------------------------------------------------------------
# handle_portfolio_compare_v0
#
# SECURITY PRINCIPLE: Read-only, sandbox-validated paths, no row data.
#
# Both snapshot paths must resolve inside SAFE_DERIVED_DIR.
# Output is a computed diff of aggregates — no raw holdings are loaded.
# ---------------------------------------------------------------------------

def handle_portfolio_compare_v0(params: dict) -> dict:
    """
    Compare two snapshot files produced by portfolio_snapshot_v0.

    Required params:
        snapshot_a (str): relative path, e.g. "data/derived/2024-01-01-before-summary.json"
        snapshot_b (str): relative path to the newer snapshot

    Returns:
        {
            "snapshot_a":               str (filename),
            "snapshot_b":               str (filename),
            "delta_total_market_value": float,
            "top_position_changes":     [{symbol, weight_pct_a, weight_pct_b, delta_pct}],
            "sector_drift":             [{sector, weight_pct_a, weight_pct_b, delta_pct}],
            "concentration_changes":    {newly_flagged: [...], dropped_below: [...]},
        }
    """
    raw_a = params.get("snapshot_a")
    raw_b = params.get("snapshot_b")

    if not raw_a or not raw_b:
        return {"error": "snapshot_a and snapshot_b are both required"}

    path_a_or_err = _resolve_one_derived_json(raw_a)
    if isinstance(path_a_or_err, dict):
        return path_a_or_err
    path_b_or_err = _resolve_one_derived_json(raw_b)
    if isinstance(path_b_or_err, dict):
        return path_b_or_err

    path_a, path_b = path_a_or_err, path_b_or_err

    try:
        snap_a = json.loads(path_a.read_text(encoding="utf-8"))
        snap_b = json.loads(path_b.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"Failed to read snapshot: {exc}"}

    # market value change
    mv_a = snap_a.get("total_market_value") or 0
    mv_b = snap_b.get("total_market_value") or 0
    delta_mv     = round(mv_b - mv_a, 2)
    delta_mv_pct = round((mv_b - mv_a) / mv_a * 100, 2) if mv_a else None

    # top position changes — union of symbols from both snapshots
    pos_a = {p["symbol"]: p["weight_pct"] for p in snap_a.get("top_positions", [])}
    pos_b = {p["symbol"]: p["weight_pct"] for p in snap_b.get("top_positions", [])}
    top_changes = [
        {
            "symbol":       sym,
            "weight_pct_a": pos_a.get(sym),
            "weight_pct_b": pos_b.get(sym),
            "delta_pct":    round((pos_b.get(sym) or 0) - (pos_a.get(sym) or 0), 2),
        }
        for sym in sorted(set(pos_a) | set(pos_b))
    ]

    # sector drift — union of sectors from both snapshots
    sec_a = snap_a.get("sector_weights_pct", {})
    sec_b = snap_b.get("sector_weights_pct", {})
    sector_drift = [
        {
            "sector":       sec,
            "weight_pct_a": sec_a.get(sec),
            "weight_pct_b": sec_b.get(sec),
            "delta_pct":    round((sec_b.get(sec) or 0) - (sec_a.get(sec) or 0), 2),
        }
        for sec in sorted(set(sec_a) | set(sec_b))
    ]

    # concentration changes
    flags_a = {f["symbol"] for f in snap_a.get("concentration_flags", [])}
    flags_b = {f["symbol"] for f in snap_b.get("concentration_flags", [])}

    # positions added / removed (uses full positions_summary if available)
    syms_a = {p["symbol"] for p in snap_a.get("positions_summary", [])}
    syms_b = {p["symbol"] for p in snap_b.get("positions_summary", [])}
    positions_added   = sorted(syms_b - syms_a)
    positions_removed = sorted(syms_a - syms_b)

    # unrealized gain change
    ug_a = snap_a.get("total_unrealized_gain")
    ug_b = snap_b.get("total_unrealized_gain")
    delta_unrealized_gain = (
        round(ug_b - ug_a, 2) if ug_a is not None and ug_b is not None else None
    )

    return {
        "snapshot_a":               path_a.name,
        "snapshot_b":               path_b.name,
        "total_market_value_a":     mv_a,
        "total_market_value_b":     mv_b,
        "delta_total_market_value": delta_mv,
        "delta_total_market_value_pct": delta_mv_pct,
        "delta_unrealized_gain":    delta_unrealized_gain,
        "top_position_changes":     top_changes,
        "sector_drift":             sector_drift,
        "positions_added":          positions_added,
        "positions_removed":        positions_removed,
        "concentration_changes": {
            "newly_flagged": sorted(flags_b - flags_a),
            "dropped_below": sorted(flags_a - flags_b),
        },
    }


# ---------------------------------------------------------------------------
# _load_llm_config
# ---------------------------------------------------------------------------

def _load_llm_config() -> dict:
    """
    Load llm_config.yaml if present; return {} (local default) if absent.
    Returns {"error": ...} on parse failure.
    """
    if not LLM_CONFIG_PATH.exists():
        return {}
    try:
        with LLM_CONFIG_PATH.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        return {"error": f"llm_config.yaml parse error: {exc}"}


# ---------------------------------------------------------------------------
# handle_portfolio_commentary_v0
#
# SECURITY PRINCIPLE: Strict data whitelist before LLM call.
#
# The commentary module (agents/ori_ia/commentary.py) enforces an explicit
# field whitelist — only aggregate totals and per-symbol analytics reach
# the LLM.  No account identifiers, file paths, or institution names are
# forwarded.  The LLM adapter defaults to local Ollama (no network egress)
# unless the user has explicitly opted in to a cloud provider via
# llm_config.yaml.
# ---------------------------------------------------------------------------

def handle_portfolio_commentary_v0(params: dict) -> dict:
    """
    Generate LLM observations and clarifying questions for the current portfolio.

    Calls portfolio_summary_v0 internally (auto-loads all manifest accounts),
    applies the strict data whitelist in commentary.py, then calls the
    configured LLM adapter.

    Optional params: (none — uses auto-load and llm_config.yaml settings)

    Returns:
        {
            "commentary":    str  — Markdown-formatted LLM response,
            "provider_used": str  — e.g. "local/llama3.2",
            "prompt_length": int  — character count (diagnostic),
        }
    """
    mode = params.get("mode", "standard")
    if mode not in ("standard", "challenge"):
        return {"error": f"Unknown commentary mode: {mode!r}. Use 'standard' or 'challenge'."}

    # Build adapter — prefer ~/.auri/config.json (wizard-configured) over
    # llm_config.yaml env-var approach so the UI wizard key always works.
    adapter = None
    try:
        from agents.ai_provider import get_provider, AIProviderError  # noqa: PLC0415
        from agents.ori_ia.llm_adapter import LLMAdapter              # noqa: PLC0415

        class _ProviderAdapter(LLMAdapter):
            """Thin shim: wraps ai_provider.AIProvider into LLMAdapter interface."""
            def __init__(self, p):
                self._p = p
                self.provider_label = p.provider_name

            def generate(self, prompt: str) -> str:
                return self._p.chat(system="You are a financial planning assistant.", user=prompt)

        _prov = get_provider()
        adapter = _ProviderAdapter(_prov)
    except Exception:
        pass  # fall through to llm_config.yaml

    if adapter is None:
        # Fall back to legacy llm_config.yaml / Ollama path
        llm_cfg = _load_llm_config()
        if "error" in llm_cfg:
            return llm_cfg
        try:
            from agents.ori_ia.llm_adapter import get_adapter  # noqa: PLC0415
            adapter = get_adapter(llm_cfg)
        except Exception as exc:
            return {"error": f"LLM adapter init failed: {exc}"}

    # Run the full summary pipeline (auto-load all accounts)
    summary = handle_portfolio_summary_v0({})
    if "error" in summary:
        return summary

    # Load full investor profile from profile.yaml (optional — graceful if absent)
    profile: dict | None = None
    _profile_path = _safe_portfolio_dir() / "profile.yaml"
    if _profile_path.exists():
        try:
            with _profile_path.open("r", encoding="utf-8") as fh:
                profile = yaml.safe_load(fh) or None
        except Exception:
            pass  # non-fatal — commentary works without profile

    # Fetch live income data (optional — non-fatal if prices unavailable)
    income_summary: dict | None = None
    try:
        prices_result = handle_portfolio_prices_v0({})
        if "error" not in prices_result:
            income_summary = prices_result.get("income_summary")
    except Exception:
        pass  # non-fatal — commentary works without income data

    # Generate commentary — whitelist enforced inside commentary.py
    try:
        from agents.ori_ia.commentary import generate_commentary  # noqa: PLC0415
        result = generate_commentary(summary, adapter, profile=profile, income_summary=income_summary, mode=mode)
    except Exception as exc:
        return {"error": f"Commentary generation failed: {exc}"}

    return {
        "commentary":    result["commentary"],
        "provider_used": adapter.provider_label,
        "prompt_length": result["prompt_length"],
        "mode":          mode,
    }


# ---------------------------------------------------------------------------
# handle_portfolio_profile_v0
#
# SECURITY PRINCIPLE: Personal data stays local.
#
# Reads questions.yaml and answers.yaml (both gitignored) and returns
# only DERIVED aggregates — risk_score, label, completeness — never the
# raw answer values.  Optionally writes derived fields back to profile.yaml
# so the dashboard can display the latest score without re-running.
# ---------------------------------------------------------------------------

def handle_portfolio_profile_v0(params: dict) -> dict:
    """
    Compute risk score from questions.yaml + answers.yaml.

    Optional params:
        write_profile (bool, default True) — if True, writes derived fields
            (risk_score, risk_label, max_drawdown_tolerance_pct, last_scored)
            back to profile.yaml so the dashboard can display them without
            re-running the scorer.

    Returns:
        {
            "risk_score":                  float   0–100,
            "risk_label":                  str,
            "completeness_pct":            float   0–100,
            "answered_count":              int,
            "total_count":                 int,
            "max_drawdown_tolerance_pct":  float | None,
            "scored_questions":            list[dict],  # per-question breakdown
        }
    """
    write_profile = params.get("write_profile", True)

    _pf_dir       = _safe_portfolio_dir()
    _questions    = _pf_dir / "questions.yaml"
    _answers      = _pf_dir / "answers.yaml"
    _profile_yaml = _pf_dir / "profile.yaml"

    if not _questions.exists():
        return {"error": f"questions.yaml not found at {_questions}"}
    if not _answers.exists():
        return {"error": f"answers.yaml not found at {_answers}"}

    try:
        from agents.ori_ia.risk_profile import load_and_score  # noqa: PLC0415
        result = load_and_score(
            questions_path=_questions,
            answers_path=_answers,
        )
    except Exception as exc:
        return {"error": f"Risk scoring failed: {exc}"}

    # Optionally write derived fields back into profile.yaml (create if needed).
    if write_profile:
        try:
            _profile_yaml.parent.mkdir(parents=True, exist_ok=True)
            profile_data = {}
            if _profile_yaml.exists():
                with _profile_yaml.open("r", encoding="utf-8") as fh:
                    profile_data = yaml.safe_load(fh) or {}
            if "derived" not in profile_data:
                profile_data["derived"] = {}
            profile_data["derived"]["risk_score"]                 = result["risk_score"]
            profile_data["derived"]["risk_label"]                 = result["risk_label"]
            profile_data["derived"]["max_drawdown_tolerance_pct"] = result["max_drawdown_tolerance_pct"]
            profile_data["derived"]["last_scored"]                = datetime.now().date().isoformat()
            with _profile_yaml.open("w", encoding="utf-8") as fh:
                yaml.dump(profile_data, fh, allow_unicode=True, sort_keys=False)
        except Exception as exc:
            # Non-fatal — score is still returned, just not persisted.
            result["profile_write_warning"] = f"Could not update profile.yaml: {exc}"

    return result


# ---------------------------------------------------------------------------
# handle_portfolio_prices_v0
#
# SECURITY / GOVERNANCE NOTE: NETWORK CALLS
#
# This is the only action in ORI Personal that makes outbound network calls.
# It is explicitly gated — never called automatically.
# Data fetched: current price, dividend rate, dividend yield per symbol.
# Source: Yahoo Finance via yfinance (public market data only).
# No personal financial data is sent outbound.
# ---------------------------------------------------------------------------

def handle_portfolio_prices_v0(params: dict) -> dict:
    """
    Fetch current market prices and dividend data for all portfolio positions.

    *** Makes outbound network calls to Yahoo Finance. ***
    Must only be called on explicit user request (Refresh Prices button).

    Returns:
        {
            "price_data":     dict  — per-symbol price + dividend info,
            "income_summary": dict  — portfolio-level income totals,
            "fetched_count":  int,
            "stale_count":    int,
            "fetched_at":     str   — ISO timestamp,
        }
    """
    _ = params  # reserved for future options (symbol filter, force_refresh, etc.)

    # Load symbol refs for Yahoo Finance symbol resolution
    symbol_refs: dict = {}
    if SYMBOL_REF_PATH.exists():
        try:
            with SYMBOL_REF_PATH.open("r", encoding="utf-8") as fh:
                ref_data = yaml.safe_load(fh) or {}
            symbol_refs = {k.upper(): v for k, v in ref_data.get("symbols", {}).items()}
        except Exception as exc:
            return {"error": f"Failed to load symbol refs: {exc}"}

    # Get current positions from the portfolio summary
    summary = handle_portfolio_summary_v0({})
    if "error" in summary:
        return summary

    positions = summary.get("positions_summary", [])
    if not positions:
        return {"error": "No positions found in portfolio summary."}

    # Fetch prices — network calls happen here
    try:
        from agents.ori_ia.market_data import fetch_prices, compute_income_summary  # noqa: PLC0415
        price_data = fetch_prices(positions, symbol_refs)
        income_summary = compute_income_summary(price_data)
    except Exception as exc:
        return {"error": f"Price fetch failed: {exc}"}

    fetched_count = sum(1 for d in price_data.values() if not d.get("stale"))
    stale_count   = sum(1 for d in price_data.values() if d.get("stale"))

    return {
        "price_data":     price_data,
        "income_summary": income_summary,
        "fetched_count":  fetched_count,
        "stale_count":    stale_count,
        "fetched_at":     datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# handle_portfolio_allocation_v0
#
# SECURITY PRINCIPLE: Read-only. Reads targets.yaml from SAFE_PORTFOLIO_DIR
# only. Computes deviation via pure analytics function — no network calls.
# ---------------------------------------------------------------------------

def handle_portfolio_allocation_v0(params: dict) -> dict:
    """
    Load targets.yaml and compare actual asset-class weights against targets.

    Returns allocation deviation rows and rebalancing trade amounts.
    Returns {"error": "no_targets_file"} if targets.yaml does not exist —
    callers should treat this as a configuration prompt, not an error.
    """
    targets_path = _safe_portfolio_dir() / "targets.yaml"
    if not targets_path.exists():
        return {"error": "no_targets_file"}

    try:
        cfg = yaml.safe_load(targets_path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:
        return {"error": f"Failed to read targets.yaml: {exc}"}

    targets = cfg.get("targets") or {}
    if not targets:
        return {"error": "targets.yaml exists but defines no targets"}

    tolerance = float(cfg.get("tolerance_pct", 5.0))

    summary = handle_portfolio_summary_v0({})
    if "error" in summary:
        return summary

    total_mv  = summary.get("total_market_value", 0.0)
    positions = summary.get("positions_summary", [])

    result = compute_allocation_deviation(positions, targets, total_mv, tolerance)

    # ── Enrich each row with a per-account-type breakdown ─────────────────
    # This lets the UI show WHERE to trade (registered vs non-registered),
    # which is essential for tax-aware rebalancing decisions.
    #
    # Build: {sector: {registered: $, non_registered: $, unclassified: $}}
    sector_acct: dict[str, dict[str, float]] = {}
    for pos in positions:
        sector = pos.get("sector") or "Unknown"
        reg    = pos.get("registered_value",     0.0) or 0.0
        nreg   = pos.get("non_registered_value", 0.0) or 0.0
        uncl   = pos.get("unclassified_value",   0.0) or 0.0
        if sector not in sector_acct:
            sector_acct[sector] = {"registered": 0.0, "non_registered": 0.0, "unclassified": 0.0}
        sector_acct[sector]["registered"]     += reg
        sector_acct[sector]["non_registered"] += nreg
        sector_acct[sector]["unclassified"]   += uncl

    for row in result.get("rows", []):
        ac   = row.get("asset_class", "")
        acct = sector_acct.get(ac, {})
        row["account_breakdown"] = {
            "registered":     round(acct.get("registered",     0.0), 2),
            "non_registered": round(acct.get("non_registered", 0.0), 2),
            "unclassified":   round(acct.get("unclassified",   0.0), 2),
        }

    return result


# ---------------------------------------------------------------------------
# handle_portfolio_suggest_targets_v0
#
# SECURITY PRINCIPLE: Read-only. Reads profile.yaml for risk_score only.
# No file writes. Pure analytics call — no network calls.
# ---------------------------------------------------------------------------

def handle_portfolio_suggest_targets_v0(params: dict) -> dict:
    """
    Read the investor risk score from profile.yaml and return a suggested
    target allocation based on the score tier.

    Returns {"error": "no_profile"} when profile.yaml does not exist.
    Returns {"error": "no_risk_score"} when the derived score is absent.
    """
    _profile_path = _safe_portfolio_dir() / "profile.yaml"
    if not _profile_path.exists():
        return {"error": "no_profile"}

    try:
        profile_data = yaml.safe_load(_profile_path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:
        return {"error": f"Failed to read profile.yaml: {exc}"}

    risk_score = (profile_data.get("derived") or {}).get("risk_score")
    if risk_score is None:
        return {"error": "no_risk_score"}

    suggestion = suggest_target_allocation(float(risk_score))
    return {
        "risk_score":    risk_score,
        "risk_label":    suggestion["risk_label"],
        "tolerance_pct": suggestion["tolerance_pct"],
        "targets":       suggestion["targets"],
    }


# ---------------------------------------------------------------------------
# handle_portfolio_save_targets_v0
#
# SECURITY PRINCIPLE: Writes ONLY to SAFE_PORTFOLIO_DIR/targets.yaml.
# Validates targets dict (non-empty, all-numeric values) before writing.
# Overwrites any existing targets.yaml — by design (user accepts suggestion).
# ---------------------------------------------------------------------------

def handle_portfolio_save_targets_v0(params: dict) -> dict:
    """
    Persist a targets dict (and optional tolerance_pct) to targets.yaml.

    Expected params:
        targets:       {sector: pct, ...}  — required, values must be numeric
        tolerance_pct: float               — optional, defaults to 5.0
    """
    targets = params.get("targets")
    if not isinstance(targets, dict) or not targets:
        return {"error": "targets must be a non-empty dict"}

    for k, v in targets.items():
        if not isinstance(v, (int, float)):
            return {"error": f"Target value for '{k}' must be numeric, got {v!r}"}

    tolerance = float(params.get("tolerance_pct", 5.0))

    data = {
        "tolerance_pct": tolerance,
        "targets": {k: float(v) for k, v in targets.items()},
    }

    targets_path = _safe_portfolio_dir() / "targets.yaml"
    try:
        targets_path.write_text(
            yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
    except OSError as exc:
        return {"error": f"Failed to write targets.yaml: {exc}"}

    return {"saved": True, "path": str(targets_path)}


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
def handle_portfolio_benchmark_v0(params: dict) -> dict:
    """
    Fetch benchmark ETF return for comparison against the portfolio.

    Expected params:
        benchmark_symbol (str): Yahoo Finance symbol, e.g. "XIU.TO"
        from_date        (str): Optional YYYY-MM-DD start date (default: Jan 1 this year)

    *** Makes outbound network calls to Yahoo Finance. ***
    """
    raw_sym = params.get("benchmark_symbol", "")
    if not isinstance(raw_sym, str) or not raw_sym.strip():
        return {"error": "benchmark_symbol must be a non-empty string"}

    from_date = params.get("from_date")
    if from_date is not None and not isinstance(from_date, str):
        return {"error": "from_date must be a YYYY-MM-DD string or omitted"}

    try:
        from agents.ori_ia.market_data import fetch_benchmark_return  # noqa: PLC0415
        return fetch_benchmark_return(raw_sym.strip(), from_date=from_date)
    except Exception as exc:
        return {"error": f"Benchmark fetch failed: {exc}"}


ACTION_HANDLERS = {
    "ping":                           handle_ping,
    "list_dir":                       handle_list_dir,
    "portfolio_import_v0":            handle_portfolio_import_v0,
    "portfolio_summary_v0":           handle_portfolio_summary_v0,
    "portfolio_snapshot_v0":          handle_portfolio_snapshot_v0,
    "portfolio_compare_v0":           handle_portfolio_compare_v0,
    "portfolio_commentary_v0":        handle_portfolio_commentary_v0,
    "portfolio_allocation_v0":        handle_portfolio_allocation_v0,
    "portfolio_suggest_targets_v0":   handle_portfolio_suggest_targets_v0,
    "portfolio_save_targets_v0":      handle_portfolio_save_targets_v0,
    "portfolio_profile_v0":           handle_portfolio_profile_v0,
    "portfolio_prices_v0":            handle_portfolio_prices_v0,
    "portfolio_benchmark_v0":         handle_portfolio_benchmark_v0,
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