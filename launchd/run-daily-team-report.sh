#!/usr/bin/env bash
set -u

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
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || true)}"
GH_BIN="${GH_BIN:-$(command -v gh 2>/dev/null || true)}"

PROMPT="run progress-report 过去24小时。必须读取并遵循 skills/progress-report/SKILL.md。这是无人值守的定时团队日报,统计窗口是过去 24 小时(即上一期日报以来),规则:
1. 输出模式 message_only:只发送飞书消息,不新建文档,不本地留存。
2. 投递目标使用 progress-report config.yaml 的 delivery.targets(团队负责人私聊),绝不发到任何群。
3. 消息是给团队负责人本人看的团队日报,固定格式:
   - 开头必须是一行团队总览:「过去 24 小时团队 N 人活跃,共 X 次提交、Y 个相关 PR,主线是……」,主线用一句话概括这一窗口内团队工作重心(从采集数据归纳,不要泛泛而谈)。
   - 然后按成员分组,每位成员条目标题必须带窗口内提交数和相关 PR 数,如「**张三**(28 提交 / 3 PR)」;PR 数取该成员窗口内有活动(新开/更新/合并)的 PR 数量,为 0 时可省略 PR 部分只写提交数;每人 2-4 句说明在做什么、进展到哪、有无阻塞;某成员的进行中 PR 写在该成员自己的条目里。如需团队级汇总(如待 review 清单),必须以「**团队待关注**」加粗标题另起一段,且每个 PR 标注负责人,不得紧贴在最后一个成员条目后面造成归属歧义。可保留必要技术词汇,不受 200 字群消息限制,但控制在一屏内。
4. 只写采集到的事实;某成员窗口内无代码活动就写「过去 24 小时无代码提交」,不要编造。
   所有 PR 引用一律写成 markdown 链接,如 [#98](https://github.com/<org>/<repo>/pull/98),URL 取自采集数据,不要凭记忆拼;消息和留档文档都要带链接。
5. 无人值守场景,跳过「发送前先给用户 review」的要求,直接发送。消息末尾附一行留档入口:[查看日报留档](<config lark.daily_log_doc.url>)。
6. 发送消息后,把同一份日报以 markdown 插入到 config.yaml 的 lark.daily_log_doc 留档文档的最前面(最新日报在最上,不要新建文档):插入内容以二级标题「## <今天日期 YYYY-MM-DD>」开头,末尾加分隔线;命令为 lark-cli docs +update --doc <token> --command block_insert_after --block-id 0 --doc-format markdown --content - --as bot(内容走 stdin,--block-id 0 表示文档开头)。留档失败不影响消息发送,但要在日志里说明。"

LOG_PREFIX="[daily-team-report]"
RUN_ID="$(date '+%Y%m%d-%H%M%S')"
CLAUDE_LOG="/tmp/lark-skills-daily-team-report.claude.${RUN_ID}.log"

cd "$REPO_DIR" || {
  echo "$LOG_PREFIX cannot cd to $REPO_DIR" >&2
  exit 1
}

echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S %Z') starting"

if [ -n "${GITHUB_TOKEN:-}" ]; then
  echo "$LOG_PREFIX using pre-set GITHUB_TOKEN"
  [ -z "${GH_TOKEN:-}" ] && export GH_TOKEN="$GITHUB_TOKEN"
elif [ -n "${GH_TOKEN:-}" ]; then
  export GITHUB_TOKEN="$GH_TOKEN"
  echo "$LOG_PREFIX using pre-set GH_TOKEN"
elif [ -x "$GH_BIN" ]; then
  GITHUB_TOKEN="$("$GH_BIN" auth token 2>/dev/null || true)"
  if [ -n "$GITHUB_TOKEN" ]; then
    export GITHUB_TOKEN
    [ -z "${GH_TOKEN:-}" ] && export GH_TOKEN="$GITHUB_TOKEN"
    echo "$LOG_PREFIX using GitHub token from active gh account"
  else
    echo "$LOG_PREFIX failed to read GitHub token from gh" >&2
  fi
else
  echo "$LOG_PREFIX GitHub token not set and gh binary not executable: $GH_BIN" >&2
fi

if [ ! -x "$CLAUDE_BIN" ]; then
  echo "$LOG_PREFIX Claude binary not executable: $CLAUDE_BIN" >&2
  exit 127
fi

echo "$LOG_PREFIX running Claude: $CLAUDE_BIN"
"$CLAUDE_BIN" -p "$PROMPT" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep" \
  >"$CLAUDE_LOG" 2>&1
claude_status=$?
cat "$CLAUDE_LOG"
if [ "$claude_status" -eq 0 ]; then
  echo "$LOG_PREFIX completed successfully"
else
  echo "$LOG_PREFIX failed with exit $claude_status" >&2
fi
exit "$claude_status"
