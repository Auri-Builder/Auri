"""
ORI_IA Canonical Holdings Schema
=================================
All portfolio CSV inputs — regardless of broker or format — are normalized
to the 14 canonical fields defined in ORI_IA_SPEC.md.

COLUMN_MAP provides flexible, case-insensitive matching from the wide variety
of real-world header names exporters use down to a single canonical name.
Add new broker-specific header variants here as they are discovered.
"""

# ---------------------------------------------------------------------------
# CANONICAL_FIELDS
#
# The authoritative list of fields every normalized holding row will carry.
# Missing or unmapped source columns default to None.
# ---------------------------------------------------------------------------
CANONICAL_FIELDS: list[str] = [
    "account_id",
    "account_type",
    "institution",
    "symbol",
    "security_name",
    "asset_class",
    "sector",
    "quantity",
    "price",
    "market_value",
    "cost_basis",
    "unrealized_gain",
    "unrealized_gain_percent",
    "currency",
]

# ---------------------------------------------------------------------------
# COLUMN_MAP
#
# Maps lowercase-stripped column header variants → canonical field name.
# First match wins when multiple source columns resolve to the same canonical
# field (a warning is logged for the duplicate).
# ---------------------------------------------------------------------------
COLUMN_MAP: dict[str, str] = {
    # ----- symbol -----
    "symbol":               "symbol",
    "ticker":               "symbol",
    "ticker symbol":        "symbol",
    "stock symbol":         "symbol",
    "stock_symbol":         "symbol",
    "security symbol":      "symbol",
    "security_symbol":      "symbol",

    # ----- security_name -----
    "security name":        "security_name",
    "security_name":        "security_name",
    "name":                 "security_name",
    "description":          "security_name",
    "security":             "security_name",
    "holding":              "security_name",
    "holding name":         "security_name",
    "investment":           "security_name",

    # ----- account_id -----
    "account id":           "account_id",
    "account_id":           "account_id",
    "acct id":              "account_id",
    "acct #":               "account_id",
    "account number":       "account_id",
    "account no":           "account_id",
    "account no.":          "account_id",
    "account num":          "account_id",

    # ----- account_type -----
    "account type":         "account_type",
    "account_type":         "account_type",
    "reg type":             "account_type",
    "registration":         "account_type",
    "registration type":    "account_type",

    # ----- institution -----
    "institution":          "institution",
    "broker":               "institution",
    "custodian":            "institution",
    "firm":                 "institution",
    "brokerage":            "institution",
    "bank":                 "institution",

    # ----- asset_class -----
    "asset class":          "asset_class",
    "asset_class":          "asset_class",
    "asset type":           "asset_class",

    # ----- sector -----
    "sector":               "sector",
    "industry":             "sector",
    "gics sector":          "sector",
    "gics industry":        "sector",

    # ----- quantity -----
    "quantity":             "quantity",
    "qty":                  "quantity",
    "shares":               "quantity",
    "units":                "quantity",
    "number of shares":     "quantity",
    "num shares":           "quantity",
    "no. of shares":        "quantity",

    # ----- price -----
    "price":                "price",
    "last price":           "price",
    "unit price":           "price",
    "close price":          "price",
    "market price":         "price",
    "current price":        "price",
    "last close":           "price",
    "closing price":        "price",
    "nav":                  "price",  # NAV for funds

    # ----- market_value -----
    "market value":         "market_value",
    "market_value":         "market_value",
    "mkt val":              "market_value",
    "mkt value":            "market_value",
    "current value":        "market_value",
    "value":                "market_value",
    "total value":          "market_value",
    "market val":           "market_value",
    "book market value":    "market_value",

    # ----- cost_basis -----
    "cost basis":           "cost_basis",
    "cost_basis":           "cost_basis",
    "book value":           "cost_basis",
    "book val":             "cost_basis",
    "avg cost":             "cost_basis",
    "average cost":         "cost_basis",
    "acb":                  "cost_basis",  # adjusted cost base (Canadian)
    "total cost":           "cost_basis",
    "book cost":            "cost_basis",

    # ----- unrealized_gain -----
    "unrealized gain":      "unrealized_gain",
    "unrealized_gain":      "unrealized_gain",
    "gain/loss":            "unrealized_gain",
    "gain loss":            "unrealized_gain",
    "unrlzd gain":          "unrealized_gain",
    "unrealized p/l":       "unrealized_gain",
    "open p&l":             "unrealized_gain",
    "unrealized pl":        "unrealized_gain",

    # ----- unrealized_gain_percent -----
    "unrealized gain %":        "unrealized_gain_percent",
    "unrealized_gain_percent":  "unrealized_gain_percent",
    "gain %":                   "unrealized_gain_percent",
    "return %":                 "unrealized_gain_percent",
    "gain/loss %":              "unrealized_gain_percent",
    "unrealized gain pct":      "unrealized_gain_percent",
    "unrealized return":        "unrealized_gain_percent",
    "unrealized p/l %":         "unrealized_gain_percent",

    # ----- currency -----
    "currency":             "currency",
    "ccy":                  "currency",
    "curr":                 "currency",
    "currency code":        "currency",
}

# ---------------------------------------------------------------------------
# NUMERIC_FIELDS
#
# These canonical fields will be parsed to float during normalization.
# All others are treated as strings.
# ---------------------------------------------------------------------------
NUMERIC_FIELDS: frozenset[str] = frozenset({
    "quantity",
    "price",
    "market_value",
    "cost_basis",
    "unrealized_gain",
    "unrealized_gain_percent",
})

# ---------------------------------------------------------------------------
# REGISTERED_ACCOUNT_TYPES
#
# Canadian registered account type identifiers.
# Comparison is done uppercase. Anything not in this set is classified
# as "non_registered"; rows with no account_type go to "unclassified".
# ---------------------------------------------------------------------------
REGISTERED_ACCOUNT_TYPES: frozenset[str] = frozenset({
    "RRSP",   # Registered Retirement Savings Plan
    "TFSA",   # Tax-Free Savings Account
    "RESP",   # Registered Education Savings Plan
    "RRIF",   # Registered Retirement Income Fund
    "LIRA",   # Locked-In Retirement Account
    "LIF",    # Life Income Fund
    "PRPP",   # Pooled Registered Pension Plan
    "DPSP",   # Deferred Profit Sharing Plan
    "FHSA",   # First Home Savings Account (2023+)
})

# Safe subdirectory (relative to PROJECT_ROOT) where portfolio CSVs must reside.
# job_runner.py enforces this — this constant is the shared source of truth.
SAFE_PORTFOLIO_SUBDIR: str = "data/portfolio"
