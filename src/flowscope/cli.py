import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .analyzer import analyze_workflow
from .models import Violation

_TIER_LABEL = {
    "hard_block": "🔴 hard\\_block",
    "requires_review": "🟠 requires\\_review",
    "warning": "🟡 warning",
    "advisory": "🔵 advisory",
}


def _write_step_summary(output: dict, warn_only: bool = False) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    wf = output.get("workflow_path", "")
    workspace = os.environ.get("GITHUB_WORKSPACE", "")
    if workspace and wf.startswith(workspace):
        wf = wf[len(workspace) :].lstrip("/")

    violations = output.get("violations", [])
    has_hard_block = any(v.get("tier") == "hard_block" for v in violations)
    has_requires_review = any(v.get("tier") == "requires_review" for v in violations)
    has_advisory = any(v.get("tier") == "advisory" for v in violations)

    if warn_only and has_hard_block:
        status = "⚠️ Audit mode — would fail (hard block)"
    elif has_hard_block:
        status = "❌ Failed"
    elif has_requires_review:
        status = "🟠 Review required (non-blocking)"
    elif has_advisory:
        status = "ℹ️ Advisory (non-blocking)"
    else:
        status = "✅ Passed"

    with open(summary_path, "a") as f:
        f.write(f"## flowscope — `{wf}`\n\n")
        if violations:
            f.write(f"**{status}** — {len(violations)} violation(s)\n\n")
            if warn_only and has_hard_block:
                f.write(
                    "> ⚠️ **Audit mode** (`--warn-only`): hard-block violations are "
                    "present but not failing the check. Enable full enforcement "
                    "(remove `--warn-only`) once these are resolved.\n\n"
                )
            elif has_requires_review and not has_hard_block:
                f.write(
                    "> 🟠 **Review required** — the check is non-blocking, but this PR "
                    "should be reviewed by a CODEOWNER on the agentic workflow file "
                    "patterns. The PR approval is the recorded human acknowledgment.\n\n"
                )
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


def _post_to_registry(output: dict, registry_url: str) -> None:
    payload = json.dumps(output).encode()
    req = urllib.request.Request(
        registry_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        print(f"flowscope: warning: registry POST failed: {exc}", file=sys.stderr)


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
    parser.add_argument(
        "--warn-only",
        action="store_true",
        default=False,
        help=(
            "Exit 0 even when violations are found. Prints a summary of what would "
            "have failed. Use during gradual rollout before enabling hard enforcement."
        ),
    )
    parser.add_argument(
        "--registry-url",
        default=os.environ.get("FLOWSCOPE_REGISTRY_URL"),
        metavar="URL",
        help=(
            "POST violations JSON to this URL for central audit tracking "
            "(env: FLOWSCOPE_REGISTRY_URL). Intended for the policy plane."
        ),
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
    _write_step_summary(output, warn_only=args.warn_only)

    if args.registry_url and not result.passed:
        _post_to_registry(output, args.registry_url)

    sys.exit(0 if (result.passed or args.warn_only) else 1)


if __name__ == "__main__":
    main()
