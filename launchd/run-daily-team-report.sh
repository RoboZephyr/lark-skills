#!/usr/bin/env bash
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${DAILY_TEAM_REPORT_ENV_FILE:-$DEFAULT_REPO_DIR/launchd/weekly-report.env}"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
REPO_DIR="${LARK_SKILLS_REPO:-$DEFAULT_REPO_DIR}"
cd "$REPO_DIR"

# Keep the Mac awake through collection, generation and delivery, including retries.
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -is -w $$ &
fi
if [ -z "${GITHUB_TOKEN:-}" ]; then
  if [ -n "${GH_TOKEN:-}" ]; then
    export GITHUB_TOKEN="$GH_TOKEN"
  else
    GITHUB_TOKEN="$("${GH_BIN:-gh}" auth token)"
    export GITHUB_TOKEN
  fi
fi
export CODEX_BIN="${CODEX_BIN:-$(command -v codex)}"
exec "${PYTHON_BIN:-python3}" skills/progress-report/scripts/run_daily_report.py "$@"
