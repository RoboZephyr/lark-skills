#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${WEEKLY_REPORT_ENV_FILE:-$DEFAULT_REPO_DIR/launchd/weekly-report.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

REPO_DIR="${LARK_SKILLS_REPO:-$DEFAULT_REPO_DIR}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || true)}"
CODEX_BIN="${CODEX_BIN:-$(command -v codex 2>/dev/null || true)}"
GH_BIN="${GH_BIN:-$(command -v gh 2>/dev/null || true)}"
WEEKLY_REPORT_GITHUB_USER="${WEEKLY_REPORT_GITHUB_USER:-}"
PROMPT="${WEEKLY_REPORT_PROMPT:-run weekly-report 上周。必须读取并遵循 skills/weekly-report/SKILL.md；使用完整上周 ISO 周范围；创建文档后自动 transfer owner 并重新授权 bot；投递到配置目标；追加索引。}"

LOG_PREFIX="[weekly-report]"
RUN_ID="$(date '+%Y%m%d-%H%M%S')"
CLAUDE_LOG="/tmp/lark-skills-weekly-report.claude.${RUN_ID}.log"
CODEX_LOG="/tmp/lark-skills-weekly-report.codex.${RUN_ID}.log"

cd "$REPO_DIR" || {
  echo "$LOG_PREFIX cannot cd to $REPO_DIR" >&2
  exit 1
}

echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S %Z') starting"

if [ -n "${GITHUB_TOKEN:-}" ]; then
  echo "$LOG_PREFIX using pre-set GITHUB_TOKEN"
  if [ -z "${GH_TOKEN:-}" ]; then
    export GH_TOKEN="$GITHUB_TOKEN"
  fi
elif [ -n "${GH_TOKEN:-}" ]; then
  export GITHUB_TOKEN="$GH_TOKEN"
  echo "$LOG_PREFIX using pre-set GH_TOKEN"
elif [ -x "$GH_BIN" ]; then
  if [ -n "$WEEKLY_REPORT_GITHUB_USER" ]; then
    token_source="gh user: $WEEKLY_REPORT_GITHUB_USER"
    GITHUB_TOKEN="$("$GH_BIN" auth token --user "$WEEKLY_REPORT_GITHUB_USER" 2>/dev/null || true)"
  else
    token_source="active gh account"
    GITHUB_TOKEN="$("$GH_BIN" auth token 2>/dev/null || true)"
  fi

  if [ -n "$GITHUB_TOKEN" ]; then
    export GITHUB_TOKEN
    if [ -z "${GH_TOKEN:-}" ]; then
      export GH_TOKEN="$GITHUB_TOKEN"
    fi
    echo "$LOG_PREFIX using GitHub token from $token_source"
  else
    echo "$LOG_PREFIX failed to read GitHub token from $token_source" >&2
  fi
else
  echo "$LOG_PREFIX GitHub token not set and gh binary not executable: $GH_BIN" >&2
fi

if [ -x "$CLAUDE_BIN" ]; then
  echo "$LOG_PREFIX trying Claude: $CLAUDE_BIN"
  "$CLAUDE_BIN" -p "/weekly-report 上周" \
    --allowedTools "Bash,Read,Write,Edit,Glob,Grep" \
    >"$CLAUDE_LOG" 2>&1
  claude_status=$?
  cat "$CLAUDE_LOG"
  if [ "$claude_status" -eq 0 ]; then
    echo "$LOG_PREFIX Claude completed successfully"
    exit 0
  fi
  echo "$LOG_PREFIX Claude failed with exit $claude_status; falling back to Codex" >&2
else
  echo "$LOG_PREFIX Claude binary not executable: $CLAUDE_BIN; falling back to Codex" >&2
fi

if [ ! -x "$CODEX_BIN" ]; then
  echo "$LOG_PREFIX Codex binary not executable: $CODEX_BIN" >&2
  exit 127
fi

echo "$LOG_PREFIX trying Codex: $CODEX_BIN"
"$CODEX_BIN" exec \
  --dangerously-bypass-approvals-and-sandbox \
  -C "$REPO_DIR" \
  "$PROMPT" \
  >"$CODEX_LOG" 2>&1
codex_status=$?
cat "$CODEX_LOG"
if [ "$codex_status" -eq 0 ]; then
  echo "$LOG_PREFIX Codex completed successfully"
else
  echo "$LOG_PREFIX Codex failed with exit $codex_status" >&2
fi
exit "$codex_status"
