#!/bin/bash
set -euo pipefail

WORKFLOW_FILE="${INPUT_WORKFLOW_FILE:?INPUT_WORKFLOW_FILE is required}"
BASELINE_FILE="${INPUT_BASELINE_FILE:-}"
EXCEPTIONS_FILE="${INPUT_EXCEPTIONS_FILE:-}"

ARGS=("$WORKFLOW_FILE")
[[ -n "$BASELINE_FILE" ]] && ARGS+=("--baseline" "$BASELINE_FILE")
[[ -n "$EXCEPTIONS_FILE" ]] && ARGS+=("--exceptions" "$EXCEPTIONS_FILE")

python -m hubflow.cli "${ARGS[@]}"
EXIT_CODE=$?

# Surface JSON output as a step output for downstream jobs
OUTPUT=$(python -m hubflow.cli "${ARGS[@]}" 2>/dev/null || true)
echo "result<<EOF" >> "$GITHUB_OUTPUT"
echo "$OUTPUT" >> "$GITHUB_OUTPUT"
echo "EOF" >> "$GITHUB_OUTPUT"

exit $EXIT_CODE
