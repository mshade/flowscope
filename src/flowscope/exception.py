from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


def _build_entry(violation: dict[str, Any], workflow: str) -> dict[str, Any]:
    return {
        "scope": violation["scope"],
        "justification": "TODO: describe why this exception is needed",
        "approved_by": "",
        "expires_at": str(date.today() + timedelta(days=90)),
        "workflow": workflow,
        "job_id": violation.get("job_id"),
    }


def scaffold(violations_json: dict[str, Any], workflow: str, output_path: Path) -> None:
    violations = [v for v in violations_json.get("violations", []) if v.get("scope")]

    existing: list[dict[str, Any]] = []
    if output_path.exists():
        with open(output_path) as fh:
            existing = json.load(fh)
        if not isinstance(existing, list):
            raise ValueError(
                f"{output_path} must contain a JSON array, got {type(existing).__name__}"
            )

    existing_keys = {(e.get("scope"), e.get("workflow")) for e in existing}
    new_entries = [
        _build_entry(v, workflow) for v in violations if (v["scope"], workflow) not in existing_keys
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as fh:
        json.dump(existing + new_entries, fh, indent=2)


def _run_scaffold(args: argparse.Namespace) -> None:
    violations_json = json.load(sys.stdin)
    scaffold(violations_json, args.workflow, args.output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Flowscope exception utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scaffold_parser = subparsers.add_parser(
        "scaffold", help="Generate exception skeleton from violations JSON (reads stdin)"
    )
    scaffold_parser.add_argument(
        "--workflow",
        required=True,
        help="Workflow file path, e.g. .github/workflows/deploy.yml",
    )
    scaffold_parser.add_argument(
        "--output",
        type=Path,
        default=Path(".github/flowscope-exceptions.json"),
        help="Path to write/merge exceptions file",
    )
    scaffold_parser.set_defaults(func=_run_scaffold)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
