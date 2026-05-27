from pathlib import Path
from typing import Any, Optional

from ruamel.yaml import YAML

from .models import CheckResult, ViolationTier
from .parser import parse_workflow
from .policy import evaluate_policy

_yaml = YAML()


def analyze_workflow(
    workflow_path: Path,
    observed_baseline: Optional[dict[str, Any]] = None,
    exceptions: Optional[list[dict]] = None,
) -> CheckResult:
    with open(workflow_path) as fh:
        raw_doc = _yaml.load(fh)

    perms = parse_workflow(workflow_path)
    violations = evaluate_policy(
        perms,
        str(workflow_path),
        raw_doc=raw_doc,
        observed_baseline=observed_baseline,
        exceptions=exceptions,
    )

    passed = not any(v.tier in (ViolationTier.HARD_BLOCK, ViolationTier.REQUIRES_REVIEW) for v in violations)

    return CheckResult(
        workflow_path=str(workflow_path),
        passed=passed,
        violations=violations,
    )
