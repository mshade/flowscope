import argparse
import json
import sys
from pathlib import Path

from .analyzer import analyze_workflow
from .models import Violation


def _violation_to_dict(v: Violation) -> dict:
    return {
        "tier": v.tier.value,
        "file_path": v.file_path,
        "line": v.line,
        "scope": v.scope,
        "job_id": v.job_id,
        "message": v.message,
        "remediation": v.remediation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze a GitHub Actions workflow for permission violations."
    )
    parser.add_argument("workflow", type=Path, help="Path to the workflow YAML file")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Path to a JSON file with observed usage baseline",
    )
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=None,
        help="Path to a JSON file with registered exceptions",
    )
    args = parser.parse_args()

    observed_baseline = None
    if args.baseline and args.baseline.exists():
        with open(args.baseline) as fh:
            observed_baseline = json.load(fh)

    exceptions = None
    if args.exceptions and args.exceptions.exists():
        with open(args.exceptions) as fh:
            exceptions = json.load(fh)

    result = analyze_workflow(args.workflow, observed_baseline=observed_baseline, exceptions=exceptions)

    output = {
        "workflow_path": result.workflow_path,
        "passed": result.passed,
        "violations": [_violation_to_dict(v) for v in result.violations],
    }
    print(json.dumps(output, indent=2))

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
