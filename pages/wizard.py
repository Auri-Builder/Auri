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

st.set_page_config(page_title="Auri · Upload Wizard", layout="wide")
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
        st.dataframe(pd.DataFrame(rows_display), use_container_width=True, hide_index=True)
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
                st.page_link("pages/1_Portfolio.py", label="Go to Portfolio and click Refresh")
                st.rerun()

    else:
        # NEW ACCOUNT PATH — one required field, everything else auto-detected
        st.markdown("**New account — select account type to save:**")

        # Try to guess account type from account ID pattern or name
        _id_upper = detected_id.upper()
        _guess_type = "RRSP"  # safe default for TD WebBroker
        if _id_upper.endswith("J"):
            _guess_type = "TFSA"
        elif _id_upper.endswith("S"):
            _guess_type = "RRSP"
        elif _id_upper.endswith("A") or _id_upper.endswith("B"):
            _guess_type = "CASH"

        _type_idx = ACCOUNT_TYPE_OPTIONS.index(_guess_type) if _guess_type in ACCOUNT_TYPE_OPTIONS else 0

        _tc1, _tc2 = st.columns([2, 1])
        account_type = _tc1.selectbox(
            "Account type",
            options=ACCOUNT_TYPE_OPTIONS,
            index=_type_idx,
            key=f"actype_{safe_name}",
            help="RRSP, TFSA, CASH (non-registered), RESP, etc."
        )
        label = _tc2.text_input(
            "Label (optional)",
            placeholder="e.g. Jeff TFSA",
            key=f"label_{safe_name}",
        )

        with st.expander("Advanced (auto-detected — change only if wrong)"):
            _ac1, _ac2, _ac3 = st.columns(3)
            institution     = _ac1.text_input("Institution", value="TD Wealth",  key=f"inst_{safe_name}")
            account_id_input = _ac2.text_input("Account ID",  value=detected_id, key=f"acid_{safe_name}",
                                               help="Auto-detected from filename.")
            currency        = _ac3.selectbox("Currency", CURRENCY_OPTIONS, index=0, key=f"cur_{safe_name}")

        if st.button(f"Save — {account_type}" + (f" · {label}" if label else ""),
                     type="primary", key=f"save_{safe_name}"):
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
                    f"Saved: {safe_name} as {account_type}. "
                    f"{total_now} account(s) now configured."
                )
                st.page_link("pages/1_Portfolio.py", label="Go to Portfolio and click Refresh →")
                st.rerun()

# ── Personal Profile ───────────────────────────────────────────────────────

st.divider()
st.subheader("Personal Profile")
st.caption(
    "Shared across all Auri agents — enter once, used by Wealth Builder and Retirement Planner. "
    "Stored locally in **data/shared_profile.yaml** (gitignored)."
)

from core.shared_profile import (  # noqa: PLC0415
    PROVINCES, RISK_LEVELS, load_shared_profile, save_shared_profile,
)

_sp = load_shared_profile()
_sp_primary = _sp.get("primary", {})
_sp_spouse  = _sp.get("spouse")

_profile_configured = bool(_sp_primary.get("current_age"))
if _profile_configured:
    st.success(
        f"Profile configured: **{_sp_primary.get('name', 'Primary')}** · "
        f"Age {_sp_primary.get('current_age')} · {_sp_primary.get('province', 'BC')} · "
        f"Retire at {_sp_primary.get('target_retirement_age', 65)}"
        + (f" · Spouse: {_sp_spouse.get('name', 'Spouse')}" if _sp_spouse else "")
    )

with st.expander("Set up personal profile", expanded=not _profile_configured):
    st.markdown("**Primary Person**")
    _pc1, _pc2, _pc3 = st.columns(3)
    _p_name  = _pc1.text_input("Name", value=_sp_primary.get("name", ""), placeholder="e.g. Jeff", key="sp_name")
    _p_age   = _pc2.number_input("Current Age", min_value=18, max_value=80,
                                  value=int(_sp_primary.get("current_age", 45)), key="sp_age")
    _p_prov  = _pc3.selectbox("Province", PROVINCES,
                               index=PROVINCES.index(_sp_primary.get("province", "BC")), key="sp_prov")

    _pc4, _pc5, _pc6 = st.columns(3)
    _p_income  = _pc4.number_input("Gross Annual Income ($)", min_value=0, max_value=1_000_000,
                                    value=int(_sp_primary.get("gross_income", 0)), step=1_000, key="sp_income")
    _p_risk    = _pc5.selectbox("Risk Tolerance", RISK_LEVELS,
                                 index=RISK_LEVELS.index(_sp_primary.get("risk_tolerance", "moderate")),
                                 key="sp_risk")
    _p_ret_age = _pc6.number_input("Target Retirement Age", min_value=40, max_value=75,
                                    value=int(_sp_primary.get("target_retirement_age", 65)), key="sp_ret")

    st.markdown("**Spouse / Partner** *(optional — leave Name blank to skip)*")
    _sc1, _sc2, _sc3 = st.columns(3)
    _s_name   = _sc1.text_input("Spouse Name", value=(_sp_spouse or {}).get("name", ""),
                                  placeholder="e.g. Julie", key="sp_s_name")
    _s_age    = _sc2.number_input("Spouse Age", min_value=18, max_value=80,
                                   value=int((_sp_spouse or {}).get("current_age", 45)), key="sp_s_age")
    _s_income = _sc3.number_input("Spouse Gross Income ($)", min_value=0, max_value=1_000_000,
                                   value=int((_sp_spouse or {}).get("gross_income", 0)),
                                   step=1_000, key="sp_s_income")

    if st.button("Save Personal Profile", type="primary", key="sp_save"):
        _new_profile: dict = {
            "primary": {
                "name":                  _p_name.strip() or "Primary",
                "current_age":           int(_p_age),
                "province":              _p_prov,
                "gross_income":          float(_p_income),
                "risk_tolerance":        _p_risk,
                "target_retirement_age": int(_p_ret_age),
            }
        }
        if _s_name.strip():
            _new_profile["spouse"] = {
                "name":         _s_name.strip(),
                "current_age":  int(_s_age),
                "gross_income": float(_s_income),
            }
        save_shared_profile(_new_profile)
        st.success("Personal profile saved.")
        st.rerun()

# ── AI Provider Configuration ──────────────────────────────────────────────

st.divider()
st.subheader("AI Provider")
st.caption(
    "Configure the AI provider used for Portfolio Commentary and portfolio insights. "
    "Your API key is stored in **~/.auri/config.json** — never committed to the repo."
)

from agents.ai_provider import (  # noqa: PLC0415
    PROVIDER_LABELS,
    is_configured,
    save_config,
)

_ai_cfg_path = Path.home() / ".auri" / "config.json"
_ai_current: dict = {}
if _ai_cfg_path.exists():
    import json as _json
    try:
        _ai_current = _json.loads(_ai_cfg_path.read_text())
    except Exception:
        pass

_cur_provider = _ai_current.get("ai_provider", "groq")
_cur_key_hint = ("*" * 8 + _ai_current["ai_api_key"][-4:]) if _ai_current.get("ai_api_key") else ""
_cur_model    = _ai_current.get("ai_model", "")

if is_configured():
    st.success(
        f"AI provider configured: **{PROVIDER_LABELS.get(_cur_provider, _cur_provider)}**"
        + (f"  ·  Key: `{_cur_key_hint}`" if _cur_key_hint else "")
    )
else:
    st.warning("No AI provider configured — Portfolio Commentary will not be available.")

with st.expander("Configure AI provider", expanded=not is_configured()):
    _provider_options = list(PROVIDER_LABELS.keys())
    _provider_labels  = list(PROVIDER_LABELS.values())
    _default_idx      = _provider_options.index(_cur_provider) if _cur_provider in _provider_options else 0

    _sel_provider = st.selectbox(
        "Provider",
        options=_provider_options,
        index=_default_idx,
        format_func=lambda k: PROVIDER_LABELS[k],
        key="ai_wizard_provider",
    )

    # Provider-specific guidance
    _guides = {
        "groq":   "Free tier — 14,400 requests/day. Get an API key at **console.groq.com** (no credit card needed).",
        "claude": "Best quality. Requires an Anthropic API key (separate from Claude.ai subscription) at **console.anthropic.com**.",
        "openai": "Requires an OpenAI API key at **platform.openai.com** (separate from ChatGPT subscription).",
        "xai":    "Requires an xAI API key at **console.x.ai** (separate from X Premium subscription).",
    }
    st.info(_guides.get(_sel_provider, ""))

    _api_key_input = st.text_input(
        "API Key",
        type="password",
        placeholder="Paste your API key here",
        value="",
        key="ai_wizard_key",
        help="Stored locally in ~/.auri/config.json — never sent anywhere except the provider's API.",
    )

    _model_input = st.text_input(
        "Model override (optional)",
        placeholder="Leave blank for default",
        value=_cur_model if _cur_provider == _sel_provider else "",
        key="ai_wizard_model",
        help="Only needed if you want a specific model version. Leave blank to use the recommended default.",
    )

    _save_btn, _clear_btn = st.columns([1, 1])
    with _save_btn:
        if st.button("Save AI configuration", type="primary", key="ai_wizard_save"):
            _key = (_api_key_input or "").strip()
            if not _key:
                # Allow saving provider+model without re-entering key if already configured
                if _ai_current.get("ai_api_key"):
                    _key = _ai_current["ai_api_key"]
                else:
                    st.error("API key is required.")
                    st.stop()
            save_config(
                provider=_sel_provider,
                api_key=_key,
                model=(_model_input.strip() or None),
            )
            st.success(f"Saved! Using **{PROVIDER_LABELS[_sel_provider]}**.")
            st.rerun()

    with _clear_btn:
        if _ai_current and st.button("Clear configuration", key="ai_wizard_clear"):
            try:
                _ai_cfg_path.unlink(missing_ok=True)
                st.success("AI configuration cleared.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not clear config: {exc}")

# ── Footer ─────────────────────────────────────────────────────────────────

st.divider()
st.page_link("Home.py", label="Go to Hub")
