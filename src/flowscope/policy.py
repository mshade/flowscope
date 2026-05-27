from __future__ import annotations

from datetime import date
from typing import Any, Optional

from .models import AccessLevel, Violation, ViolationTier, WorkflowPermissions

# Actions known to make dynamic API calls under the job token
AGENTIC_ACTIONS: set[str] = {
    "anthropics/claude-code-action",
}

_WRITE_ALL_SCOPE = "write-all"
_IMPLICIT_FULL_SCOPE = "implicit-full-access"


def _is_exception_active(exc: dict[str, Any]) -> bool:
    try:
        expires = date.fromisoformat(str(exc["expires_at"]))
    except (KeyError, ValueError):
        return False
    return expires >= date.today()


def _scope_is_excepted(scope: str, exceptions: list[dict], workflow_path: str) -> bool:
    return any(
        exc.get("scope") == scope
        and _is_exception_active(exc)
        and (not exc.get("workflow") or exc.get("workflow") == workflow_path)
        for exc in exceptions
    )


def _job_names_from_doc(raw_doc: Optional[dict]) -> list[str]:
    if not raw_doc:
        return []
    return list((raw_doc.get("jobs") or {}).keys())


def _steps_for_job(raw_doc: Optional[dict], job_id: str) -> list[dict]:
    if not raw_doc:
        return []
    return (raw_doc.get("jobs") or {}).get(job_id, {}).get("steps") or []


def _job_uses_agentic_action(raw_doc: Optional[dict], job_id: str) -> bool:
    for step in _steps_for_job(raw_doc, job_id):
        uses = step.get("uses") or ""
        action_name = uses.split("@")[0] if "@" in uses else uses
        if action_name in AGENTIC_ACTIONS:
            return True
    return False


def _workflow_triggers(raw_doc: Optional[dict]) -> set[str]:
    """Return the set of trigger names from `on:`.

    Handles all three YAML forms: string, list, dict. Also handles the YAML 1.1
    quirk where unquoted `on` may parse as boolean True.
    """
    if not raw_doc:
        return set()
    on = raw_doc.get("on")
    if on is None:
        on = raw_doc.get(True)
    if on is None:
        return set()
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return {str(k) for k in on.keys()}
    return set()


def _write_scoped_locations(perms: WorkflowPermissions) -> list[tuple[Optional[str], str]]:
    """Yield (job_id, scope_name) for every write-scoped location.

    job_id is None for workflow-level writes.
    """
    locations: list[tuple[Optional[str], str]] = []
    for scope, lvl in perms.workflow_level.items():
        if lvl == AccessLevel.WRITE:
            locations.append((None, scope))
    for job_id, job_perms in perms.jobs.items():
        for scope, lvl in job_perms.scopes.items():
            if lvl == AccessLevel.WRITE:
                locations.append((job_id, scope))
    return locations


def evaluate_policy(
    perms: WorkflowPermissions,
    workflow_path: str,
    raw_doc: Optional[dict],
    observed_baseline: Optional[dict[str, Any]] = None,
    exceptions: Optional[list[dict]] = None,
) -> list[Violation]:
    exceptions = exceptions or []
    violations: list[Violation] = []

    # ── Rule 1: write-all ────────────────────────────────────────────────────
    if perms.write_all:
        if not _scope_is_excepted(_WRITE_ALL_SCOPE, exceptions, workflow_path=workflow_path):
            violations.append(
                Violation(
                    tier=ViolationTier.HARD_BLOCK,
                    file_path=workflow_path,
                    line=None,
                    scope=_WRITE_ALL_SCOPE,
                    job_id=None,
                    message="permissions: write-all grants full token access",
                    remediation=(
                        "Replace with explicit per-job permission blocks scoped to "
                        "minimum required access. See docs/permissions-guide.md."
                    ),
                )
            )
        return violations  # no further analysis useful when write-all

    # ── Rule 2: implicit full access (permissions: {}) ───────────────────────
    if perms.implicit_full_access:
        if not _scope_is_excepted(_IMPLICIT_FULL_SCOPE, exceptions, workflow_path=workflow_path):
            violations.append(
                Violation(
                    tier=ViolationTier.HARD_BLOCK,
                    file_path=workflow_path,
                    line=None,
                    scope=_IMPLICIT_FULL_SCOPE,
                    job_id=None,
                    message=(
                        "permissions: {} (empty map) is equivalent to write-all on GitHub Actions"
                    ),
                    remediation=(
                        "Declare explicit scopes at the job level. "
                        "Remove the empty top-level permissions block."
                    ),
                )
            )
        return violations

    # ── Rule 3: workflow-level write with unscoped jobs ──────────────────────
    write_scopes_at_workflow = {
        s for s, lvl in perms.workflow_level.items() if lvl == AccessLevel.WRITE
    }

    if write_scopes_at_workflow:
        all_job_ids = _job_names_from_doc(raw_doc) or list(perms.jobs.keys())
        unscoped_jobs = [jid for jid in all_job_ids if jid not in perms.jobs]

        # If raw_doc is absent and no job-level scopes exist, there are unscoped jobs
        # (we can't enumerate them but we know they exist via the workflow_level write).
        has_unscoped = bool(unscoped_jobs) or (not raw_doc and not perms.jobs)

        if has_unscoped:
            for scope in write_scopes_at_workflow:
                if not _scope_is_excepted(scope, exceptions, workflow_path=workflow_path):
                    if unscoped_jobs:
                        msg = (
                            f"Workflow-level write scope '{scope}' applies to "
                            f"unscoped jobs: {unscoped_jobs}. "
                            "Job-level permissions blocks must override it."
                        )
                        rem = (
                            f"Add an explicit permissions block to each job "
                            f"({', '.join(unscoped_jobs)}) to restrict the "
                            f"'{scope}' write scope to only jobs that need it."
                        )
                    else:
                        msg = (
                            f"Workflow-level write scope '{scope}' is declared but "
                            "job enumeration was unavailable — all jobs may be exposed "
                            "to this write scope without job-level scoping."
                        )
                        rem = (
                            f"Add explicit per-job permissions blocks to restrict "
                            f"the '{scope}' write scope to only jobs that need it."
                        )
                    violations.append(
                        Violation(
                            tier=ViolationTier.HARD_BLOCK,
                            file_path=workflow_path,
                            line=None,
                            scope=scope,
                            job_id=None,
                            message=msg,
                            remediation=rem,
                        )
                    )

    # ── Rule 4: agentic step with write scope and no baseline ────────────────
    # Without raw_doc, step data is unavailable; Rule 4 cannot detect agentic actions
    all_job_ids = _job_names_from_doc(raw_doc) or list(perms.jobs.keys())
    for job_id in all_job_ids:
        if not _job_uses_agentic_action(raw_doc, job_id):
            continue

        job_perms = perms.jobs.get(job_id)
        effective_scopes = job_perms.scopes if job_perms else perms.workflow_level
        has_write = any(lvl == AccessLevel.WRITE for lvl in effective_scopes.values())

        if has_write and observed_baseline is None:
            violations.append(
                Violation(
                    tier=ViolationTier.REQUIRES_REVIEW,
                    file_path=workflow_path,
                    line=None,
                    scope=None,
                    job_id=job_id,
                    message=(
                        f"Job '{job_id}' uses an agentic action with write scope(s) "
                        "but has no observed usage baseline. "
                        "Agentic steps make dynamic API calls — over-permissioning "
                        "has a higher blast radius."
                    ),
                    remediation=(
                        "Have a security or platform team member review and approve "
                        "this PR, or instrument the runner with the flowscope "
                        "post-job hook to establish an observed baseline."
                    ),
                )
            )

    # ── Rule 5: pull_request_target with any write scope ────────────────────
    # pull_request_target runs in the base repo context (with secrets and
    # write tokens) but can be triggered by fork PRs. If the workflow checks
    # out the PR's HEAD, attacker-controlled code executes with write access.
    # Well-documented attack vector; the safe default is HARD_BLOCK.
    triggers = _workflow_triggers(raw_doc)
    if "pull_request_target" in triggers and not _scope_is_excepted(
        "pull_request_target", exceptions, workflow_path=workflow_path
    ):
        for job_id, scope in _write_scoped_locations(perms):
            location = f"job '{job_id}'" if job_id else "workflow level"
            violations.append(
                Violation(
                    tier=ViolationTier.HARD_BLOCK,
                    file_path=workflow_path,
                    line=None,
                    scope="pull_request_target",
                    job_id=job_id,
                    message=(
                        f"Workflow triggered by 'pull_request_target' has write scope "
                        f"'{scope}' at {location}. This trigger runs in the base repo "
                        "context with secrets and the GITHUB_TOKEN but fires on fork "
                        "PRs — if the workflow checks out the PR's HEAD ref, "
                        "attacker-controlled code executes with write access. "
                        "Canonical fork-PR-poisoning attack pattern."
                    ),
                    remediation=(
                        "Switch the trigger to 'pull_request' (which gives fork PRs a "
                        f"read-only token), or remove the '{scope}' write scope. If "
                        "'pull_request_target' is required (e.g. labeling/comment bot), "
                        "register a 'pull_request_target' exception with justification "
                        "AND verify the workflow never checks out the PR's HEAD ref "
                        "(use the base ref only)."
                    ),
                )
            )

    # ── Rule 6: workflow_run with any write scope ────────────────────────────
    # workflow_run inherits implicit secrets access from the triggering workflow.
    # Common legitimate use is post-CI deploy, but it warrants human review:
    # the chain creates a privilege-escalation path if upstream is compromised.
    if "workflow_run" in triggers and not _scope_is_excepted(
        "workflow_run", exceptions, workflow_path=workflow_path
    ):
        for job_id, scope in _write_scoped_locations(perms):
            location = f"job '{job_id}'" if job_id else "workflow level"
            violations.append(
                Violation(
                    tier=ViolationTier.REQUIRES_REVIEW,
                    file_path=workflow_path,
                    line=None,
                    scope="workflow_run",
                    job_id=job_id,
                    message=(
                        f"Workflow triggered by 'workflow_run' has write scope "
                        f"'{scope}' at {location}. workflow_run inherits implicit "
                        "secrets access from the triggering workflow — if the "
                        "upstream workflow is compromised, this chain extends the "
                        "blast radius. Legitimate (e.g. deploy-after-CI) but "
                        "warrants explicit human review."
                    ),
                    remediation=(
                        "Confirm the upstream workflow is trustworthy and that the "
                        f"'{scope}' write scope on {location} is genuinely required. "
                        "Recorded human acknowledgment via CODEOWNERS-routed PR "
                        "approval; or register a 'workflow_run' exception."
                    ),
                )
            )

    return violations
