#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="${LARK_SKILLS_REPO:-$DEFAULT_REPO_DIR}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || true)}"
CODEX_BIN="${CODEX_BIN:-$(command -v codex 2>/dev/null || true)}"
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
