"""
ORI Upload Wizard — Phase B

Accepts broker CSV exports, strips preamble, validates format, and lets the user
configure account metadata before writing to data/portfolio/.

data/portfolio/ is NOT written until the user explicitly clicks "Save to accounts.yaml".
"""

import re
import shutil
import tempfile
from pathlib import Path

import streamlit as st
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_DIR = PROJECT_ROOT / "data" / "portfolio"
ACCOUNTS_YAML_PATH = PORTFOLIO_DIR / "accounts.yaml"

# ---------------------------------------------------------------------------
# Imports from backend (read-only)
# ---------------------------------------------------------------------------
from agents.ori_ia.extract import extract_holdings_table   # shared preamble stripper
from agents.ori_ia.normalize import normalize_csv
from agents.ori_ia.schema import REGISTERED_ACCOUNT_TYPES

ACCOUNT_TYPE_OPTIONS = sorted(REGISTERED_ACCOUNT_TYPES | {"RESP"}) + ["CASH", "Other"]
CURRENCY_OPTIONS = ["CAD", "USD"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_account_id(filename: str) -> str:
    """Auto-detect account ID from TD Wealth filename pattern: {ID}-holdings-{date}.csv"""
    m = re.match(r"^([A-Z0-9]+)-holdings-", filename, re.IGNORECASE)
    return m.group(1).upper() if m else ""


def _load_accounts() -> dict:
    if not ACCOUNTS_YAML_PATH.exists():
        return {}
    with ACCOUNTS_YAML_PATH.open("r", encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("accounts", {})


def _save_accounts(accounts: dict) -> None:
    ACCOUNTS_YAML_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ACCOUNTS_YAML_PATH.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            {"accounts": accounts},
            fh,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )


def _safe_filename(name: str) -> str | None:
    """Return the bare filename if it passes safety checks, else None."""
    safe = Path(name).name
    if not re.match(r"^[\w\-. ]+\.csv$", safe, re.IGNORECASE):
        return None
    return safe


def _find_existing_by_account_id(account_id: str, accounts: dict) -> tuple[str, dict] | tuple[None, None]:
    """
    Return (filename, metadata) for an existing accounts.yaml entry whose
    account_id matches, or (None, None) if not found.
    """
    if not account_id:
        return None, None
    for fname, meta in accounts.items():
        if meta.get("account_id", "").upper() == account_id.upper():
            return fname, meta
    return None, None


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Upload Wizard — ORI", layout="wide")
st.title("Upload Wizard")
st.caption("Add CSV portfolio exports · configure account metadata · local only · no network calls")

# ── Existing accounts (read-only) ──────────────────────────────────────────

existing_accounts = _load_accounts()

if existing_accounts:
    with st.expander(f"Existing accounts ({len(existing_accounts)} entries)"):
        rows_display = [
            {
                "File": fname,
                "Account Type": meta.get("account_type", ""),
                "Institution": meta.get("institution", ""),
                "Account ID": meta.get("account_id", ""),
                "Label": meta.get("label", ""),
            }
            for fname, meta in existing_accounts.items()
        ]
        import pandas as pd
        st.dataframe(pd.DataFrame(rows_display), width="stretch", hide_index=True)
else:
    st.info("No accounts.yaml yet — add your first account below.")

st.divider()

# ── File uploader ──────────────────────────────────────────────────────────

uploaded_files = st.file_uploader(
    "Upload CSV export(s)",
    type=["csv"],
    accept_multiple_files=True,
    help="Broker CSV exports (TD Wealth or compatible). Raw files are validated here; "
    "nothing is written to data/portfolio/ until you click Save.",
)

# ── Session state ──────────────────────────────────────────────────────────

if "validated" not in st.session_state:
    # filename → {row_count, fields, unmapped, tmp_path, error}
    st.session_state.validated = {}

if "saved" not in st.session_state:
    # filenames that have been successfully saved this session
    st.session_state.saved = set()

# ── Per-file processing ────────────────────────────────────────────────────

for uf in uploaded_files:
    st.subheader(uf.name)

    # Filename safety check
    safe_name = _safe_filename(uf.name)
    if safe_name is None:
        st.error(f"Rejected: filename contains invalid characters — {uf.name!r}")
        continue

    # Validate once per session
    if uf.name not in st.session_state.validated:
        raw_tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        raw_tmp.write(uf.read())
        raw_tmp.close()

        clean_tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        clean_tmp.close()

        try:
            extract_holdings_table(Path(raw_tmp.name), Path(clean_tmp.name))
            Path(raw_tmp.name).unlink(missing_ok=True)
            rows, fields, unmapped = normalize_csv(Path(clean_tmp.name))
            st.session_state.validated[uf.name] = {
                "row_count": len(rows),
                "fields": fields,
                "unmapped": unmapped,
                "tmp_path": clean_tmp.name,
                "error": None,
            }
        except Exception as exc:
            Path(raw_tmp.name).unlink(missing_ok=True)
            Path(clean_tmp.name).unlink(missing_ok=True)
            st.session_state.validated[uf.name] = {
                "error": str(exc),
                "tmp_path": None,
            }

    v = st.session_state.validated[uf.name]

    # Show error or parse result
    if v.get("error"):
        st.error(f"Parse failed: {v['error']}")
        continue

    row_count = v["row_count"]
    fields = v["fields"]
    unmapped = v.get("unmapped", [])
    unmapped_note = f"  ·  {len(unmapped)} unmapped: {unmapped}" if unmapped else ""
    st.success(f"✓  {row_count} rows  ·  {len(fields)} fields detected{unmapped_note}")

    # Already saved this session
    if uf.name in st.session_state.saved:
        st.info("Saved to accounts.yaml this session.")
        continue

    existing_accounts = _load_accounts()

    # Already in accounts.yaml under this exact filename
    if safe_name in existing_accounts:
        st.info("Already in accounts.yaml — no changes needed.")
        continue

    # ── Detect if this is an UPDATE to an existing account ─────────────────
    detected_id  = _extract_account_id(safe_name)
    old_filename, old_meta = _find_existing_by_account_id(detected_id, existing_accounts)

    if old_filename and old_meta:
        # UPDATE PATH — same account_id, new filename (new export date)
        old_label = old_meta.get("label") or old_meta.get("account_id", old_filename)
        st.info(
            f"Detected as an update to **{old_label}**  \n"
            f"Current file: `{old_filename}`  →  New file: `{safe_name}`"
        )

        delete_old = st.checkbox(
            f"Also delete old file `{old_filename}` from data/portfolio/",
            value=True,
            key=f"del_{safe_name}",
        )

        if st.button(f"Replace — update accounts.yaml to use {safe_name}", key=f"update_{safe_name}"):
            tmp_path = v.get("tmp_path")
            if not tmp_path or not Path(tmp_path).exists():
                st.error("Temp file missing — please re-upload the file.")
            else:
                PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy(tmp_path, PORTFOLIO_DIR / safe_name)

                # Replace the old key with the new filename, preserving metadata
                current = _load_accounts()
                entry = dict(current.pop(old_filename, old_meta))
                current[safe_name] = entry
                _save_accounts(current)

                if delete_old:
                    old_path = PORTFOLIO_DIR / old_filename
                    old_path.unlink(missing_ok=True)

                st.session_state.saved.add(uf.name)
                st.success(
                    f"Updated: `{old_filename}` → `{safe_name}` in accounts.yaml."
                    + (f" Old file deleted." if delete_old else "")
                )
                st.page_link("app.py", label="Go to Dashboard and click Refresh")
                st.rerun()

    else:
        # NEW ACCOUNT PATH
        with st.form(key=f"form_{safe_name}"):
            col1, col2 = st.columns(2)
            with col1:
                account_type = st.selectbox(
                    "Account type",
                    options=ACCOUNT_TYPE_OPTIONS,
                    index=0,
                )
                institution = st.text_input("Institution", value="TD Wealth")
            with col2:
                account_id_input = st.text_input(
                    "Account ID",
                    value=detected_id,
                    help="Auto-detected from filename where possible.",
                )
                label = st.text_input("Label", placeholder="e.g. Child Name RESP (optional)")
            currency = st.selectbox("Currency", options=CURRENCY_OPTIONS, index=0)

            submitted = st.form_submit_button("Save to accounts.yaml")

        if submitted:
            tmp_path = v.get("tmp_path")
            if not tmp_path or not Path(tmp_path).exists():
                st.error("Temp file missing — please re-upload the file.")
            else:
                PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy(tmp_path, PORTFOLIO_DIR / safe_name)

                current = _load_accounts()
                if safe_name not in current:
                    entry = {"account_type": account_type, "institution": institution}
                    if account_id_input:
                        entry["account_id"] = account_id_input
                    if label:
                        entry["label"] = label
                    entry["currency"] = currency
                    current[safe_name] = entry
                    _save_accounts(current)

                st.session_state.saved.add(uf.name)
                total_now = len(_load_accounts())
                st.success(
                    f"Saved: {safe_name}. "
                    f"{total_now} account(s) now configured in accounts.yaml."
                )
                st.page_link("app.py", label="Go to Dashboard and click Refresh")
                st.rerun()

# ── Footer ─────────────────────────────────────────────────────────────────

st.divider()
st.page_link("app.py", label="Go to Dashboard")
