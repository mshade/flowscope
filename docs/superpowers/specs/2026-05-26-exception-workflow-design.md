# Exception Request Workflow Design

**Date:** 2026-05-26
**Status:** Approved

## Problem

When flowscope blocks a workflow, developers have no self-service path to request an exception. Exceptions must be hand-edited into a JSON file, and there is no structured approval mechanism.

## Goals

- Developer can request an exception without installing any tooling or leaving GitHub
- Security team approval is structurally enforced via CODEOWNERS
- No new workflow files added to consuming repos
- Exceptions are scoped to the specific workflow that triggered the violation
- Per-repo storage with a clear future path to central aggregation

## Non-goals

- Central/org-wide exception store (future work)
- Exception expiry enforcement or renewal reminders (future work)
- Automated approval or merging

---

## Architecture

### Exception storage

Exceptions live in `.github/flowscope-exceptions.json` in each consuming repo. CODEOWNERS protects this file, requiring security team review on any PR that modifies it.

### Exception schema

```json
{
  "scope": "contents:write",
  "justification": "TODO: describe why this exception is needed",
  "approved_by": "",
  "expires_at": "YYYY-MM-DD",
  "workflow": ".github/workflows/deploy.yml",
  "job_id": "deploy"
}
```

| Field | Required by policy engine | Purpose |
|---|---|---|
| `scope` | yes | Permission scope being excepted |
| `expires_at` | yes | ISO date; policy engine rejects expired entries |
| `workflow` | yes (new) | Scopes the exception to a specific workflow file |
| `justification` | no | Human-readable reason; filled by developer before review |
| `approved_by` | no | Optional; security reviewer may fill before approving. The PR merge record and CODEOWNERS audit trail are the authoritative approval evidence |
| `job_id` | no | Informational context for reviewer |

`status` is removed. The three gates are scope+workflow match, expiry, and CODEOWNERS-enforced merge approval. To revoke an exception, delete the entry or let it expire.

### Policy engine changes

`_is_exception_active` drops the `status` check. An entry is active if it is not expired.

`_scope_is_excepted` gains an optional `workflow_path` parameter. When matching:

- If the exception entry has a `workflow` field, it must match `workflow_path`
- If the exception entry has no `workflow` field, it matches any workflow (backwards compatible, for deliberate repo-wide grants)

This prevents a single approved exception from silently suppressing violations in new workflows added later.

### New action input

`action.yml` gains a boolean input `create-exception-pr` (default: `false`). When `true` and violations are detected, the action creates a self-service exception request PR.

### New Python subcommand: `flowscope exception scaffold`

Reads violations JSON from stdin. Writes (or merges into) `.github/flowscope-exceptions.json` with one skeleton entry per violation. Merging preserves any existing entries so previously approved exceptions are not clobbered.

### Entrypoint additions

After the main analysis, if `create-exception-pr` is set and violations were found:

1. Derive branch name: `flowscope/exception-<workflow-stem>` where stem is the workflow filename without path or extension (e.g. `deploy` from `.github/workflows/deploy.yml`)
2. Check if branch already exists: `git ls-remote --heads origin flowscope/exception-<stem>`
3. If branch exists: skip creation, find the open PR for that branch, post a comment on the original PR pointing to it
4. If branch does not exist:
   - `git checkout -b flowscope/exception-<stem>`
   - Run `flowscope exception scaffold` to write/merge the exceptions file
   - `git commit` + `git push`
   - `gh pr create --draft` with the body below
   - If running in a PR context: post a comment on the original PR with a link to the exception PR

### Draft PR body template

```
**Flowscope detected permission violations in `<workflow>`.**

This draft PR adds a skeleton exception entry to `.github/flowscope-exceptions.json`.

**Developer: before marking ready for review**
1. Edit `.github/flowscope-exceptions.json` in this PR
2. Fill in `justification` — describe why this permission is needed
3. Confirm or adjust `expires_at`
4. Mark this PR as ready for review

**Security team:** approval of this PR constitutes the formal exception grant.
CODEOWNERS enforcement requires your review before merge.
The exception is active immediately on merge — no further action required.
```

### Required permissions in consuming repo workflow

```yaml
permissions:
  contents: write
  pull-requests: write
```

If these are absent and `create-exception-pr: true`, the entrypoint emits a clear error message rather than failing silently.

---

## Idempotency

Branch names are deterministic (`flowscope/exception-<stem>`), so re-running the action on subsequent pushes to the same PR will detect the existing branch and skip creation. A comment is posted on each run pointing to the existing exception PR.

---

## Edge cases

| Case | Behavior |
|---|---|
| Action runs on a branch push with no associated PR | Exception branch and PR are still created; the "comment on original PR" step is skipped |
| `.github/flowscope-exceptions.json` already exists | Scaffold merges new entries in; existing entries are preserved |
| `contents: write` / `pull-requests: write` missing | Clear error message; main analysis exit code is still written to `$GITHUB_OUTPUT` |
| Exception branch exists but PR was closed | Detected as existing branch; comments on original PR with branch link |

---

## Testing

**Unit tests — policy engine:**
- Exception with matching `workflow` field suppresses the violation
- Exception with non-matching `workflow` field does not suppress
- Exception with no `workflow` field suppresses regardless (backwards compat)
- Expired exception does not suppress (no status field involved)
- Existing tests updated to remove `status` field from fixtures

**Unit tests — scaffold subcommand:**
- Produces correct JSON shape for a single violation
- Merges into an existing file without clobbering approved entries
- `workflow` and `job_id` fields are present in each entry
- Expiry defaults to 90 days from scaffold run date

**Integration:** entrypoint shell logic (branch, PR, comment) is verified manually against a real consuming repo.

---

## Future path: central aggregation

Per-repo exceptions are the current default. If org-wide visibility becomes a requirement, a nightly aggregation job can collect `flowscope-exceptions.json` from all repos via the GitHub API without changing the per-repo storage model or the consuming repo's workflow.
