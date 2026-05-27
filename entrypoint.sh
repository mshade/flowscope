#!/bin/bash
set -euo pipefail

WORKFLOW_FILE="${INPUT_WORKFLOW_FILE:?INPUT_WORKFLOW_FILE is required}"
BASELINE_FILE="${INPUT_BASELINE_FILE:-}"
EXCEPTIONS_FILE="${INPUT_EXCEPTIONS_FILE:-}"
CREATE_EXCEPTION_PR="${INPUT_CREATE_EXCEPTION_PR:-false}"

ARGS=("$WORKFLOW_FILE")
[[ -n "$BASELINE_FILE" ]] && ARGS+=("--baseline" "$BASELINE_FILE")
[[ -n "$EXCEPTIONS_FILE" ]] && ARGS+=("--exceptions" "$EXCEPTIONS_FILE")

# Capture output and exit code without triggering set -e on non-zero exit
set +e
OUTPUT=$(python -m flowscope.cli "${ARGS[@]}")
EXIT_CODE=$?
set -e

# Surface JSON output as a step output for downstream jobs
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "result<<EOF" >> "$GITHUB_OUTPUT"
    echo "$OUTPUT" >> "$GITHUB_OUTPUT"
    echo "EOF" >> "$GITHUB_OUTPUT"
fi

# Print to stdout for CI logs
echo "$OUTPUT"

# Write a markdown summary to the Actions step summary panel.
# This avoids the double-annotation problem that occurs when ::error:: commands
# are emitted alongside GHA's built-in "Process completed with exit code 1" annotation.
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    FLOWSCOPE_OUTPUT="$OUTPUT" python3 - <<'PYEOF'
import json, os

data = json.loads(os.environ["FLOWSCOPE_OUTPUT"])
workspace = os.environ.get("GITHUB_WORKSPACE", "")
wf = data.get("workflow_path", "")
if workspace and wf.startswith(workspace):
    wf = wf[len(workspace):].lstrip("/")

passed = data.get("passed", True)
violations = data.get("violations", [])

status = "✅ Passed" if passed else "❌ Failed"
summary_path = os.environ["GITHUB_STEP_SUMMARY"]

tier_label = {
    "hard_block":      "🔴 hard\_block",
    "requires_review": "🟠 requires\_review",
    "warning":         "🟡 warning",
    "advisory":        "🔵 advisory",
}

with open(summary_path, "a") as f:
    f.write(f"## flowscope — `{wf}`\n\n")
    f.write(f"**{status}**")
    if violations:
        f.write(f" — {len(violations)} violation(s)\n\n")
        f.write("| Tier | Message | Remediation |\n")
        f.write("|------|---------|-------------|\n")
        for v in violations:
            tier = v.get("tier", "")
            label = tier_label.get(tier, tier)
            msg = v.get("message", "").replace("|", "\\|")
            fix = v.get("remediation", "").replace("|", "\\|")
            f.write(f"| {label} | {msg} | {fix} |\n")
    else:
        f.write("\n")
    f.write("\n")
PYEOF
fi

# Exception PR creation — opt-in, only when violations exist
if [[ "$CREATE_EXCEPTION_PR" == "true" && "$EXIT_CODE" -ne 0 ]]; then
    WORKFLOW_STEM=$(basename "${WORKFLOW_FILE}" .yml)
    BRANCH="flowscope/exception-${WORKFLOW_STEM}"

    if git ls-remote --exit-code --heads origin "${BRANCH}" > /dev/null 2>&1; then
        # Branch already exists — find the open PR and comment on the original
        EXCEPTION_PR_URL=$(gh pr list --head "${BRANCH}" --json url --jq '.[0].url // empty' 2>/dev/null || echo "")
        PR_NUMBER=$(python -c "import json,os; d=json.load(open(os.environ['GITHUB_EVENT_PATH'])); print(d.get('pull_request',{}).get('number',''))" 2>/dev/null || echo "")
        if [[ -n "$PR_NUMBER" ]]; then
            if [[ -n "$EXCEPTION_PR_URL" ]]; then
                COMMENT_BODY="Flowscope blocked this workflow. An exception request is already open: ${EXCEPTION_PR_URL}"
            else
                COMMENT_BODY="Flowscope blocked this workflow. An exception request branch already exists: \`${BRANCH}\`"
            fi
            gh pr comment "$PR_NUMBER" --body "$COMMENT_BODY"
        fi
    else
        # Create the exception branch and PR
        git config user.name "github-actions[bot]"
        git config user.email "github-actions[bot]@users.noreply.github.com"
        git checkout -b "${BRANCH}"

        echo "$OUTPUT" | python -m flowscope.exception scaffold --workflow "${WORKFLOW_FILE}"

        git add .github/flowscope-exceptions.json 2>/dev/null || true
        if git diff --cached --quiet; then
            echo "No new exception entries generated; skipping PR creation." >&2
            exit "$EXIT_CODE"
        fi

        git commit -m "chore: flowscope exception request for ${WORKFLOW_STEM}"
        git push origin "${BRANCH}"

        PR_BODY="**Flowscope detected permission violations in \`${WORKFLOW_FILE}\`.**

This draft PR adds a skeleton exception entry to \`.github/flowscope-exceptions.json\`.

**Developer: before marking ready for review**
1. Edit \`.github/flowscope-exceptions.json\` in this PR
2. Fill in \`justification\` — describe why this permission is needed
3. Confirm or adjust \`expires_at\`
4. Mark this PR as ready for review

**Security team:** approval of this PR constitutes the formal exception grant.
CODEOWNERS enforcement requires your review before merge.
The exception is active immediately on merge — no further action required."

        EXCEPTION_PR_URL=$(gh pr create \
            --draft \
            --title "flowscope: exception request for ${WORKFLOW_STEM}" \
            --body "$PR_BODY" \
            --head "${BRANCH}" | tail -1)

        PR_NUMBER=$(python -c "import json,os; d=json.load(open(os.environ['GITHUB_EVENT_PATH'])); print(d.get('pull_request',{}).get('number',''))" 2>/dev/null || echo "")
        if [[ -n "$PR_NUMBER" ]]; then
            gh pr comment "$PR_NUMBER" --body "Flowscope blocked this workflow. An exception request PR has been created: ${EXCEPTION_PR_URL}

Fill in \`justification\` and confirm \`expires_at\`, then mark the PR ready for security team review."
        fi
    fi
fi

exit $EXIT_CODE
