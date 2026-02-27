import logging
import yaml
from pathlib import Path

log = logging.getLogger(__name__)


def load_symbol_ref(ref_path: Path) -> dict:
    """
    Load symbol → {sector, asset_class} from a YAML file.

    All keys are normalized to uppercase on load so that lookups are
    case-insensitive (broker exports may use 'vfv', 'VFV', or 'Vfv').

    Returns an empty dict if the file is absent — enrichment is optional and
    the handler degrades gracefully without it (sectors remain "unknown").

    Raises ValueError on parse or schema errors so the caller can surface them
    as a job failure rather than silently producing wrong analytics.
    """
    if not ref_path.exists():
        log.debug("Symbol reference file not found at %s — skipping enrichment", ref_path)
        return {}

    with ref_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict) or "symbols" not in data:
        raise ValueError(
            f"symbols.yaml must have a top-level 'symbols' key: {ref_path}"
        )

    symbols = data["symbols"]
    if not isinstance(symbols, dict):
        raise ValueError(
            "symbols.yaml 'symbols' must be a ticker → metadata mapping"
        )

    # Normalize all keys to uppercase so lookups are case-insensitive.
    return {k.strip().upper(): v for k, v in symbols.items()}


def enrich_rows(rows: list[dict], symbol_ref: dict) -> None:
    """
    Fill None sector and asset_class values from symbol_ref. Mutates rows in-place.

    Symbol lookup is normalized to strip().upper() to match the uppercase keys
    produced by load_symbol_ref — broker export capitalization never causes misses.

    Priority order (highest wins):
      1. CSV-supplied value (already in row after normalize_csv)
      2. Manifest-injected value (already in row after metadata injection)
      3. Symbol reference value (this function)
      4. None / "unknown" fallback (analytics layer)

    Unknown symbols are silently skipped — partial reference coverage is expected.
    """
    for row in rows:
        raw_symbol = row.get("symbol")
        if not raw_symbol:
            continue
        ref = symbol_ref.get(raw_symbol.strip().upper())
        if not ref:
            continue
        if row.get("sector") is None and ref.get("sector"):
            row["sector"] = ref["sector"]
        if row.get("asset_class") is None and ref.get("asset_class"):
            row["asset_class"] = ref["asset_class"]
