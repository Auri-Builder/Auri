"""
ORI Submit Job CLI
==================
A minimal ORI-native command-line tool for submitting a single job to the
job runner and printing the result.

Usage (always invoke as a module so project root is on sys.path):

    python -m core.submit_job_cli <action> [key=value ...] [--timeout N] [--no-approval]

Examples:

    python -m core.submit_job_cli ping

    python -m core.submit_job_cli portfolio_import_v0 \\
        csv_path=data/portfolio/holdings.csv

    python -m core.submit_job_cli portfolio_summary_v0 \\
        csv_path=data/portfolio/holdings.csv \\
        concentration_threshold=0.10 \\
        top_n=5

    python -m core.submit_job_cli portfolio_summary_v0 \\
        csv_path=data/portfolio/holdings.csv \\
        account_type=TFSA

Flags:
    --timeout N      Seconds to wait for a result (default: 30)
    --no-approval    Skip the interactive approval gate (dev/smoke-test only)

Exit codes:
    0 — job completed (status ok or failed — check result JSON)
    1 — no result received (denied, timed out, or submission rejected)
"""

import sys
import json
import argparse

from core.oricore import submit_and_wait, load_config


def _parse_params(param_list: list[str]) -> dict:
    """
    Parse a list of "key=value" strings into a typed params dict.

    Type coercion order: int → float → bool → str.
    Malformed entries (no '=') are warned about and skipped.
    """
    params: dict = {}
    for item in param_list:
        if "=" not in item:
            print(
                f"Warning: ignoring malformed param {item!r} (expected key=value)",
                file=sys.stderr,
            )
            continue

        key, _, raw_value = item.partition("=")
        key = key.strip()

        # Attempt numeric coercion before falling back to string
        coerced: int | float | bool | str = raw_value
        for cast in (int, float):
            try:
                coerced = cast(raw_value)
                break
            except ValueError:
                pass
        else:
            # No numeric cast succeeded — check for bool literals
            if raw_value.lower() == "true":
                coerced = True
            elif raw_value.lower() == "false":
                coerced = False
            # else stays as the raw string

        params[key] = coerced

    return params


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit an ORI job and print the result.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "action",
        help="Job action name (e.g. ping, portfolio_import_v0, portfolio_summary_v0)",
    )
    parser.add_argument(
        "params",
        nargs="*",
        metavar="key=value",
        help="Job parameters as key=value pairs",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        metavar="N",
        help="Seconds to wait for a result (default: 30)",
    )
    parser.add_argument(
        "--no-approval",
        action="store_true",
        help="Skip the interactive approval gate (dev/smoke-test mode only)",
    )
    args = parser.parse_args()

    params = _parse_params(args.params)
    config = load_config()

    if args.no_approval:
        config["approval_required"] = False

    result = submit_and_wait(args.action, params, config, timeout=args.timeout)

    if result:
        print(json.dumps(result, indent=2))
        sys.exit(0)
    else:
        print("No result received (job denied, timed out, or submission rejected).",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
