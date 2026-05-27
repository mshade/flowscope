from __future__ import annotations

from datetime import date
from typing import Any, Optional

from .models import AccessLevel, JobPermissions, Violation, ViolationTier, WorkflowPermissions

# Actions known to make dynamic API calls under the job token
AGENTIC_ACTIONS: set[str] = {
    "anthropics/claude-code-action",
}

_WRITE_ALL_SCOPE = "write-all"
_IMPLICIT_FULL_SCOPE = "implicit-full-access"


def _is_exception_active(exc: dict[str, Any]) -> bool:
    if exc.get("status") != "active":
        return False
    try:
        expires = date.fromisoformat(str(exc["expires_at"]))
    except (KeyError, ValueError):
        return False
    return expires >= date.today()


def _scope_is_excepted(scope: str, exceptions: list[dict]) -> bool:
    return any(
        exc.get("scope") == scope and _is_exception_active(exc)
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
        uses = step.get("uses", "")
        action_name = uses.split("@")[0] if "@" in uses else uses
        if action_name in AGENTIC_ACTIONS:
            return True
    return False


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
        if not _scope_is_excepted(_WRITE_ALL_SCOPE, exceptions):
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
        if not _scope_is_excepted(_IMPLICIT_FULL_SCOPE, exceptions):
            violations.append(
                Violation(
                    tier=ViolationTier.HARD_BLOCK,
                    file_path=workflow_path,
                    line=None,
                    scope=_IMPLICIT_FULL_SCOPE,
                    job_id=None,
                    message=(
                        "permissions: {} (empty map) is equivalent to write-all "
                        "on GitHub Actions"
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
                if not _scope_is_excepted(scope, exceptions):
                    violations.append(
                        Violation(
                            tier=ViolationTier.HARD_BLOCK,
                            file_path=workflow_path,
                            line=None,
                            scope=scope,
                            job_id=None,
                            message=(
                                f"Workflow-level write scope '{scope}' applies to "
                                f"unscoped jobs: {unscoped_jobs}. "
                                "Job-level permissions blocks must override it."
                            ),
                            remediation=(
                                f"Add an explicit permissions block to each job "
                                f"({', '.join(unscoped_jobs)}) to restrict the "
                                f"'{scope}' write scope to only jobs that need it."
                            ),
                        )
                    )

    # ── Rule 4: agentic step with write scope and no baseline ────────────────
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
                    tier=ViolationTier.WARNING,
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
                        "Instrument the runner with the hubflow post-job hook to "
                        "establish an observed baseline, or manually justify each "
                        "write scope with an inline comment."
                    ),
                )
            )

    return violations
