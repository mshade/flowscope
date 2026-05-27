import argparse
import json
import os
import sys
from pathlib import Path

from .analyzer import analyze_workflow
from .models import Violation


_TIER_LABEL = {
    "hard_block": "🔴 hard\\_block",
    "requires_review": "🟠 requires\\_review",
    "warning": "🟡 warning",
    "advisory": "🔵 advisory",
}


def _write_step_summary(output: dict) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    wf = output.get("workflow_path", "")
    workspace = os.environ.get("GITHUB_WORKSPACE", "")
    if workspace and wf.startswith(workspace):
        wf = wf[len(workspace):].lstrip("/")

    passed = output.get("passed", True)
    violations = output.get("violations", [])
    status = "✅ Passed" if passed else "❌ Failed"

    with open(summary_path, "a") as f:
        f.write(f"## flowscope — `{wf}`\n\n")
        if violations:
            f.write(f"**{status}** — {len(violations)} violation(s)\n\n")
            f.write("| Tier | Message | Remediation |\n")
            f.write("|------|---------|-------------|\n")
            for v in violations:
                label = _TIER_LABEL.get(v.get("tier", ""), v.get("tier", ""))
                msg = v.get("message", "").replace("|", "\\|")
                fix = v.get("remediation", "").replace("|", "\\|")
                f.write(f"| {label} | {msg} | {fix} |\n")
        else:
            f.write(f"**{status}**\n")
        f.write("\n")


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

    result = analyze_workflow(
        args.workflow, observed_baseline=observed_baseline, exceptions=exceptions
    )

    output = {
        "workflow_path": result.workflow_path,
        "passed": result.passed,
        "violations": [_violation_to_dict(v) for v in result.violations],
    }
    print(json.dumps(output, indent=2))
    _write_step_summary(output)

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
