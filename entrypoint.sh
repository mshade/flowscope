#!/bin/bash
set -euo pipefail

WORKFLOW_FILE="${INPUT_WORKFLOW_FILE:?INPUT_WORKFLOW_FILE is required}"
BASELINE_FILE="${INPUT_BASELINE_FILE:-}"
EXCEPTIONS_FILE="${INPUT_EXCEPTIONS_FILE:-}"

ARGS=("$WORKFLOW_FILE")
[[ -n "$BASELINE_FILE" ]] && ARGS+=("--baseline" "$BASELINE_FILE")
[[ -n "$EXCEPTIONS_FILE" ]] && ARGS+=("--exceptions" "$EXCEPTIONS_FILE")

# Run once, capture output; || true prevents set -e from exiting early
OUTPUT=$(python -m flowscope.cli "${ARGS[@]}" || true)
EXIT_CODE=$?

# Surface JSON output as a step output for downstream jobs
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "result<<EOF" >> "$GITHUB_OUTPUT"
    echo "$OUTPUT" >> "$GITHUB_OUTPUT"
    echo "EOF" >> "$GITHUB_OUTPUT"
fi

# Print to stdout for CI logs
echo "$OUTPUT"

exit $EXIT_CODE
