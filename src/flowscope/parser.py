from pathlib import Path
from ruamel.yaml import YAML
from .models import AccessLevel, JobPermissions, WorkflowPermissions

_yaml = YAML()
_yaml.preserve_quotes = True


def _parse_access_level(value: str) -> AccessLevel:
    match value.lower():
        case "read":
            return AccessLevel.READ
        case "write":
            return AccessLevel.WRITE
        case "none":
            return AccessLevel.NONE
        case _:
            return AccessLevel.READ  # unknown defaults to read (conservative)


def _parse_scope_map(raw: dict) -> dict[str, AccessLevel]:
    return {k: _parse_access_level(v) for k, v in raw.items()}


def parse_workflow(path: Path) -> WorkflowPermissions:
    with open(path) as fh:
        doc = _yaml.load(fh)

    result = WorkflowPermissions()

    top_perms = doc.get("permissions")
    if top_perms == "write-all":
        result.write_all = True
    elif isinstance(top_perms, dict) and len(top_perms) == 0:
        result.implicit_full_access = True
    elif isinstance(top_perms, dict):
        result.workflow_level = _parse_scope_map(top_perms)
    # top_perms is None → no top-level block, which is fine

    for job_id, job_data in (doc.get("jobs") or {}).items():
        job_perms = job_data.get("permissions")
        if isinstance(job_perms, dict) and job_perms:
            result.jobs[job_id] = JobPermissions(
                job_id=job_id,
                scopes=_parse_scope_map(job_perms),
            )

    return result
