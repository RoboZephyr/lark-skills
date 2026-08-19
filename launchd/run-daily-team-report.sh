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
6. 发送消息后,把同一份日报以 markdown 插入到 config.yaml 的 lark.daily_log_doc 留档文档的最前面(最新日报在最上,不要新建文档):插入内容以二级标题「## <今天日期 YYYY-MM-DD>」开头,末尾加分隔线;命令为 lark-cli docs +update --doc <token> --command block_insert_after --block-id 0 --doc-format markdown --content - --as bot(内容走 stdin,--block-id 0 表示文档开头)。留档失败不影响消息发送,但要在日志里说明。
7. 执行方式硬性要求:所有命令(尤其是数据采集脚本)必须前台同步执行并等待其完成,严禁把任何命令放到后台(run_in_background)执行后结束回合等通知——本任务跑在 claude -p 非交互模式下,回合结束进程就退出,后台任务会被直接丢弃。最终输出必须包含实际发送成功返回的 message_id(om_ 开头);消息没有真正发出去就绝不能输出 message_id。"

LOG_PREFIX="[daily-team-report]"
RUN_ID="$(date '+%Y%m%d-%H%M%S')"
CLAUDE_LOG="/tmp/lark-skills-daily-team-report.claude.${RUN_ID}.log"

# 可用环境变量覆盖(见 weekly-report.env)
MAX_ATTEMPTS="${DAILY_TEAM_REPORT_MAX_ATTEMPTS:-3}"
RETRY_DELAY="${DAILY_TEAM_REPORT_RETRY_DELAY:-120}"
RUN_TIMEOUT="${DAILY_TEAM_REPORT_TIMEOUT:-1200}"
NET_WAIT="${DAILY_TEAM_REPORT_NET_WAIT:-180}"

cd "$REPO_DIR" || {
  echo "$LOG_PREFIX cannot cd to $REPO_DIR" >&2
  exit 1
}

echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S %Z') starting (run_id=$RUN_ID)"

# ---------- 全程持有 caffeinate ----------
# 关键:launchd 在机器睡眠时靠 DarkWake 把任务叫起来,而 DarkWake 会在维护窗口结束时
# 立刻睡回去(2026-08-16 就是 21:03:50 唤醒、21:03:52 回睡,claude 拿不到网络直接 ENOTFOUND)。
# 所以断言必须从脚本第一步就持有,而不是等到调用 claude 时才拿——那时早就睡回去了。
# -i 阻止空闲休眠;-s 阻止系统休眠(仅 AC 供电时生效);-w 让 caffeinate 跟随本脚本生命周期自动退出。
CAFFEINATE_BIN="$(command -v caffeinate 2>/dev/null || true)"
if [ -n "$CAFFEINATE_BIN" ]; then
  "$CAFFEINATE_BIN" -is -w $$ &
  echo "$LOG_PREFIX holding caffeinate -is for the whole run (pid $!)"
else
  echo "$LOG_PREFIX caffeinate not found; machine may sleep mid-run" >&2
fi

# ---------- 失败告警:三次都失败时私发一条飞书消息,避免漏发被静默 ----------
alert_failure() {
  local reason="$1"
  local target
  target="$(python3 -c '
import sys
sys.path.insert(0, "skills/progress-report/scripts")
from pathlib import Path
from collect_progress import load_config
cfg = load_config(Path("skills/progress-report/config.yaml"))
targets = (cfg.get("delivery") or {}).get("targets") or []
print(targets[0].get("id", "") if targets else "")
' 2>/dev/null || true)"

  if [ -z "$target" ]; then
    echo "$LOG_PREFIX cannot alert: no delivery target in config" >&2
    return
  fi
  if ! command -v lark-cli >/dev/null 2>&1; then
    echo "$LOG_PREFIX cannot alert: lark-cli not found" >&2
    return
  fi

  local body
  body="**⚠️ 团队日报生成失败**

- 时间: $(date '+%Y-%m-%d %H:%M:%S %Z')
- 原因: ${reason}
- 已重试: ${MAX_ATTEMPTS} 次
- 日志: ${CLAUDE_LOG}

最后 10 行输出:
\`\`\`
$(tail -n 10 "$CLAUDE_LOG" 2>/dev/null || echo '(无输出)')
\`\`\`

补发方式: 在仓库里跑 \`/progress-report\`,统计窗口指定为漏掉的那一段。"

  if lark-cli im +messages-send --user-id "$target" --markdown "$body" --as bot >/dev/null 2>&1; then
    echo "$LOG_PREFIX failure alert sent"
  else
    echo "$LOG_PREFIX failed to send failure alert" >&2
  fi
}

# ---------- 等网络:覆盖 Mac 从睡眠中被唤醒、网络还没起来的场景 ----------
wait_for_network() {
  local waited=0
  while [ "$waited" -lt "$NET_WAIT" ]; do
    if curl -sS --max-time 8 -o /dev/null https://api.github.com/zen 2>/dev/null; then
      [ "$waited" -gt 0 ] && echo "$LOG_PREFIX network ready after ${waited}s"
      return 0
    fi
    sleep 10
    waited=$((waited + 10))
  done
  echo "$LOG_PREFIX network still unreachable after ${NET_WAIT}s" >&2
  return 1
}

# ---------- 超时看门狗:macOS 没有 timeout(1),自己轮询 ----------
run_with_timeout() {
  local secs="$1"; shift
  "$@" &
  local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$secs" ]; then
      echo "$LOG_PREFIX timeout after ${secs}s, killing pid $pid" >&2
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill -TERM "$pid" 2>/dev/null || true
      sleep 5
      pkill -KILL -P "$pid" 2>/dev/null || true
      kill -KILL "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 124
    fi
    sleep 5
    waited=$((waited + 5))
  done
  wait "$pid"
}

# ---------- GitHub token ----------
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
  alert_failure "Claude binary not executable: $CLAUDE_BIN"
  exit 127
fi

# ---------- 主循环:最多 MAX_ATTEMPTS 次,每次带超时 ----------
claude_status=1
attempt=1

while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "$LOG_PREFIX attempt ${attempt}/${MAX_ATTEMPTS} at $(date '+%H:%M:%S')"

  if ! wait_for_network; then
    echo "$LOG_PREFIX skipping attempt ${attempt}: no network" >&2
    claude_status=1
  else
    run_with_timeout "$RUN_TIMEOUT" "$CLAUDE_BIN" -p "$PROMPT" \
      --allowedTools "Bash,Read,Write,Edit,Glob,Grep" \
      >"$CLAUDE_LOG" 2>&1
    claude_status=$?
    cat "$CLAUDE_LOG"
  fi

  if [ "$claude_status" -eq 0 ]; then
    # 退出码 0 不代表真的发了:2026-08-19 曾出现 claude 把采集脚本放后台后直接结束回合,
    # 进程 exit 0 但消息根本没发。必须在输出里看到发送成功的 message_id(om_ 开头)才算成功。
    if grep -qE 'om_[0-9a-z]{8,}' "$CLAUDE_LOG"; then
      echo "$LOG_PREFIX completed successfully on attempt ${attempt}"
      exit 0
    fi
    echo "$LOG_PREFIX exit 0 but no message_id in output; treating as failure" >&2
    claude_status=1
  fi

  if [ "$claude_status" -eq 124 ]; then
    echo "$LOG_PREFIX attempt ${attempt} timed out after ${RUN_TIMEOUT}s" >&2
  else
    echo "$LOG_PREFIX attempt ${attempt} failed with exit ${claude_status}" >&2
  fi

  if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    echo "$LOG_PREFIX retrying in ${RETRY_DELAY}s"
    sleep "$RETRY_DELAY"
  fi
  attempt=$((attempt + 1))
done

echo "$LOG_PREFIX failed after ${MAX_ATTEMPTS} attempts (last exit ${claude_status})" >&2
if [ "$claude_status" -eq 124 ]; then
  alert_failure "连续 ${MAX_ATTEMPTS} 次超时(每次上限 ${RUN_TIMEOUT}s)"
else
  alert_failure "连续 ${MAX_ATTEMPTS} 次失败(最后退出码 ${claude_status})"
fi
exit "$claude_status"
