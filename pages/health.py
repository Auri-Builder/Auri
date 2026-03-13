"""
ORI Health Checks — pages/health.py

Read-only page that validates every entry in accounts.yaml:
  - file exists and is inside the sandbox (data/portfolio/)
  - preamble can be stripped (extract_holdings_table succeeds)
  - normalize_csv returns > 0 rows

No files are permanently written. Temp files used for extract/normalize
are always deleted after each check.
"""

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
from core._paths import PROJECT_ROOT, get_data_dir  # noqa: F401
PORTFOLIO_DIR = get_data_dir() / "portfolio"
ACCOUNTS_YAML_PATH = PORTFOLIO_DIR / "accounts.yaml"

# ---------------------------------------------------------------------------
# Imports from backend (read-only)
# ---------------------------------------------------------------------------
from agents.ori_ia.extract import extract_holdings_table
from agents.ori_ia.normalize import normalize_csv

# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title("Health Checks")
st.caption("Validates accounts.yaml + CSV files · read-only · no writes · no network calls")

# ── accounts.yaml existence ─────────────────────────────────────────────────

if not ACCOUNTS_YAML_PATH.exists():
    st.error("accounts.yaml not found in data/portfolio/")
    st.info("Use the Upload Wizard to add your first account.")
    st.page_link("pages/wizard.py", label="Go to Upload Wizard")
    st.stop()

try:
    with ACCOUNTS_YAML_PATH.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    accounts = raw.get("accounts", {})
except yaml.YAMLError as exc:
    st.error(f"accounts.yaml parse error: {exc}")
    st.stop()

if not isinstance(accounts, dict) or not accounts:
    st.warning("accounts.yaml has no entries.")
    st.page_link("pages/wizard.py", label="Go to Upload Wizard")
    st.stop()

st.success(f"accounts.yaml found — {len(accounts)} account(s) configured")

# ── Per-account validation ──────────────────────────────────────────────────

rows = []

for fname, meta in accounts.items():
    if not isinstance(meta, dict):
        rows.append({
            "file": fname, "exists": False, "sandbox_ok": False,
            "extract_ok": False, "normalized_rows": 0, "fields_detected": 0,
            "status": "ERROR",
            "hint": "Manifest entry is not a valid key/value mapping",
        })
        continue

    csv_path = PORTFOLIO_DIR / fname

    # 1. Existence + extension check
    if not csv_path.exists():
        rows.append({
            "file": fname, "exists": False, "sandbox_ok": True,
            "extract_ok": False, "normalized_rows": 0, "fields_detected": 0,
            "status": "ERROR",
            "hint": "Re-upload in Wizard",
        })
        continue

    if csv_path.suffix.lower() != ".csv":
        rows.append({
            "file": fname, "exists": True, "sandbox_ok": True,
            "extract_ok": False, "normalized_rows": 0, "fields_detected": 0,
            "status": "ERROR",
            "hint": "File is not a .csv",
        })
        continue

    # 2. Sandbox containment — resolve symlinks before the check so a symlink
    #    pointing outside data/portfolio/ cannot bypass the boundary.
    try:
        resolved = csv_path.resolve()
        sandbox_ok = resolved.is_relative_to(PORTFOLIO_DIR.resolve())
    except Exception:
        sandbox_ok = False

    if not sandbox_ok:
        rows.append({
            "file": fname, "exists": True, "sandbox_ok": False,
            "extract_ok": False, "normalized_rows": 0, "fields_detected": 0,
            "status": "ERROR",
            "hint": "Path resolves outside data/portfolio/ — check for symlinks",
        })
        continue

    # 3. Extract preamble (temp file only — no permanent write)
    raw_tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    raw_tmp_path = Path(raw_tmp.name)
    raw_tmp.write(csv_path.read_bytes())
    raw_tmp.close()

    clean_tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    clean_tmp_path = Path(clean_tmp.name)
    clean_tmp.close()

    try:
        extract_holdings_table(raw_tmp_path, clean_tmp_path)
        extract_ok = True
    except ValueError:
        raw_tmp_path.unlink(missing_ok=True)
        clean_tmp_path.unlink(missing_ok=True)
        rows.append({
            "file": fname, "exists": True, "sandbox_ok": True,
            "extract_ok": False, "normalized_rows": 0, "fields_detected": 0,
            "status": "ERROR",
            "hint": "Export 'Holdings' CSV from broker; file may be activity/summary",
        })
        continue
    finally:
        raw_tmp_path.unlink(missing_ok=True)

    # 4. Normalize (temp file only — delete after)
    try:
        norm_rows, detected_fields, _ = normalize_csv(clean_tmp_path)
    except (ValueError, OSError) as exc:
        clean_tmp_path.unlink(missing_ok=True)
        rows.append({
            "file": fname, "exists": True, "sandbox_ok": True,
            "extract_ok": True, "normalized_rows": 0, "fields_detected": 0,
            "status": "ERROR",
            "hint": f"Normalization failed: {exc}",
        })
        continue
    finally:
        clean_tmp_path.unlink(missing_ok=True)

    row_count = len(norm_rows)
    if row_count == 0:
        status, hint = "WARN", "File parsed but no holdings rows found"
    else:
        status, hint = "OK", ""

    rows.append({
        "file": fname,
        "exists": True,
        "sandbox_ok": True,
        "extract_ok": True,
        "normalized_rows": row_count,
        "fields_detected": len(detected_fields),
        "status": status,
        "hint": hint,
    })

# ── Render table ─────────────────────────────────────────────────────────────

df = pd.DataFrame(
    rows,
    columns=[
        "file", "exists", "sandbox_ok", "extract_ok",
        "normalized_rows", "fields_detected", "status", "hint",
    ],
)


def _colour_row(row):
    """Apply background colour to every cell based on the status column."""
    val = row["status"]
    colour = (
        "#ccffcc" if val == "OK"
        else "#ffffcc" if val == "WARN"
        else "#ffcccc"
    )
    return [f"background-color: {colour}"] * len(row)


styled = df.style.apply(_colour_row, axis=1)
st.dataframe(styled, use_container_width=True, hide_index=True)

# ── Summary line ─────────────────────────────────────────────────────────────

ok_count   = sum(1 for r in rows if r["status"] == "OK")
warn_count = sum(1 for r in rows if r["status"] == "WARN")
err_count  = sum(1 for r in rows if r["status"] == "ERROR")

if err_count:
    st.error(f"{err_count} account(s) have errors — see hints above.")
elif warn_count:
    st.warning(f"{warn_count} account(s) have warnings.")
else:
    st.success(f"All {ok_count} account(s) healthy.")

# ── Footer ────────────────────────────────────────────────────────────────────

st.divider()
col1, col2 = st.columns(2)
with col1:
    if st.button("Go to Hub"):
        st.switch_page("pages/hub.py")
with col2:
    st.page_link("pages/wizard.py", label="Go to Upload Wizard")
