---
name: progress-report
description: Generate and deliver a plain-language, decision-oriented Lark/Feishu progress update from recent repository changes or a specific GitHub PR. Use when the user asks to 同步进度, 生成进度汇报, 发项目进展到群, 这个 PR 做了什么, summarize recent code progress, publish engineering progress, explain a PR, or describe what changed, why that approach was chosen, what it means for the workflow, and what to do next based on commits, branches, and PRs.
---

# Progress Report

生成一份面向团队同步的工程进度报告：从 GitHub 仓库最近代码改动或指定 PR 采集数据，先形成可追溯事实底稿，再改写成平白、面向决策的同步内容，说明“做了什么 / 为什么这样做 / 对工作流有什么意义 / 还有什么待确认 / 下一步是什么”，创建飞书文档并发送到配置的用户或群聊。

## Prerequisites

| 依赖 | 验证命令 |
|---|---|
| lark-cli | `lark-cli auth status` |
| GitHub token | `gh auth status` 或环境变量 `GITHUB_TOKEN` |
| python3 + ruamel.yaml | `python3 -c 'import ruamel.yaml'` |

## Input

支持两种同步维度。

**时间范围模式**：

- `今天` → 今天 00:00 到现在
- `昨天` → 昨天 00:00 到 23:59
- `本周` → 本周一到今天
- `上周` → 上一个完整 ISO 周
- `最近 N 天` → 最近 N 天
- 未指定 → 使用 `config.yaml` 的 `report.default_days`，默认 7 天

**PR 模式**：

- GitHub PR URL：`https://github.com/org/repo/pull/123`
- 简写：`org/repo#123`
- 只有一个 `github.repos` 时可只写：`#123` 或 `123`

当用户说“这个 PR 做了什么”“同步这个 PR 的进度”“根据当前 PR 写汇报”时，优先使用 PR 模式，而不是时间范围模式。

## Execution Flow

### Step 1: 读取配置

读取 `skills/progress-report/config.yaml`。默认配置通过 `extends_config` 继承 `skills/weekly-report/config.yaml`，避免重复维护：

- `github.repos`
- `github.token`
- `team.members`
- `team.gitlab_to_github`
- `lark.permissions`
- `delivery.targets`

`progress-report/config.yaml` 中显式配置的同名字段覆盖继承配置。

### Step 2: 采集代码进度

运行脚本生成 Markdown 报告和原始 JSON。

时间范围模式：

```bash
python3 skills/progress-report/scripts/collect_progress.py \
  --config skills/progress-report/config.yaml \
  --range "<今天|昨天|本周|上周|最近 N 天>" \
  --output /tmp/progress_report.md \
  --raw-output /tmp/progress_report_raw.json
```

PR 模式：

```bash
python3 skills/progress-report/scripts/collect_progress.py \
  --config skills/progress-report/config.yaml \
  --pr "<PR URL | owner/repo#123 | #123>" \
  --output /tmp/progress_report.md \
  --raw-output /tmp/progress_report_raw.json
```

脚本采集口径：

- 默认统计所有分支的 commits（`report.include_all_branches: true`），按 SHA 去重，避免只看 `main`
- 同时采集时间范围内更新过的 PR，以及仍打开的 PR
- PR 模式只采集该 PR 的 commits、files 和 PR 状态，不受时间范围限制
- 只保留能匹配团队成员 GitHub login 或 extra_emails 的提交
- 报告必须只使用采集到的数据，不能编造

### Step 3: Agent 叙事改写

读取 `/tmp/progress_report.md` 和 `/tmp/progress_report_raw.json`，把脚本生成的事实底稿改写成团队能直接理解的进度同步。默认结构：

```markdown
# 项目进度同步 (<scope>)

## 结论
用 1-3 句说明现在进展到哪里，以及这次同步最重要的变化。

## 做了什么
用业务/工作流语言说明完成的事情，不要直接堆 commit 标题。

## 为什么这样做
说明选择这个方案的原因、取舍或规避的风险。

## 对工作流的意义
说明它让团队后续工作更顺、成本更可控、链路更可审计，或减少了什么阻塞。

## 仍需确认
只写真实不确定项，不能把猜测写成事实。

## 下一步
写清楚后续行动，不确定来源的行动项标注为“建议”。

## 代码证据
保留 PR、commit、文件范围等可追溯证据。
```

必须遵守：

- 每个已完成事项都要能追溯到 commit、PR 或 PR file diff
- “接下来”只能来自打开 PR、近期分支名、commit 标题中的明确线索，或标注为“建议”
- 不确定的事项放到“待确认”，不要写成事实
- 群消息优先讲人话：先讲结论，再讲原因，再讲意义，再讲下一步
- 不要把群消息写成 changelog、commit digest 或测试日志；SHA、文件清单、OQ 编号只作为证据或链接出现
- 如果代码事实不足以支撑“为什么”和“意义”，保留为待确认或请用户补上下文，不要编造

### Step 4: 创建飞书文档

复用 `lark-doc-deliver` 的流程。把报告复制到当前工作目录，然后创建文档：

```bash
cp /tmp/progress_report.md ./progress_report.md
lark-cli docs +create \
  --title "项目进度同步 (<scope>)" \
  --markdown @progress_report.md \
  --as bot
```

从输出 JSON 提取：

- `doc_url`: `.data.doc_url`
- `document_id`: `.data.doc_id`

### Step 5: 自动权限转移

创建文档后必须立刻按 `lark.permissions` 配置执行权限转移。`progress-report/config.yaml` 默认继承 `weekly-report/config.yaml`，因此应直接使用继承后的 `doc_owner_open_ids` 和 `bot_open_id`。

如果 `doc_owner_open_ids[0]` 或 `bot_open_id` 为空，停止投递并报告配置缺失；不要留下只有 bot 可见的文档。

`transfer_owner` 和 `permission.members.create` 是 high-risk-write 操作，必须带 `--yes`，因为 owner 和 bot open_id 已由配置显式登记。

```bash
lark-cli drive permission.members transfer_owner \
  --params '{"token":"<document_id>","type":"docx","stay_put":"<stay_put>","remove_old_owner":"<remove_old_owner>","old_owner_perm":"<old_owner_perm>","need_notification":"false"}' \
  --data '{"member_type":"<member_type>","member_id":"<第一个 doc_owner_open_ids>"}' \
  --as bot \
  --yes
```

然后重新授权 bot：

```bash
lark-cli drive permission.members create \
  --params '{"token":"<document_id>","type":"docx","need_notification":"false"}' \
  --data '{"member_type":"openid","member_id":"<bot_open_id>","perm":"full_access"}' \
  --as bot \
  --yes
```

如 `doc_owner_open_ids` 有多个成员，再给其余成员授权：

```bash
lark-cli drive permission.members create \
  --params '{"token":"<document_id>","type":"docx","need_notification":"false"}' \
  --data '{"member_type":"<member_type>","member_id":"<open_id>","perm":"full_access"}' \
  --as bot \
  --yes
```

权限操作失败时记录错误；如果 owner transfer 失败，不要发送群消息，避免投递不可访问的文档。

### Step 6: 消息投递

构造群消息，包含摘要和文档链接：

```markdown
**项目进度同步 (<scope>)**

同步一下 <项目/模块> 的关键进展。

我们现在完成了 <用平白语言描述的变化>。

这次选择 <方案>，主要是因为 <原因/风险/取舍>。

这对工作流的意义是：<影响>。

目前仍需确认：<不确定项>。

下一步：<行动项>。

[查看完整进度文档](<doc_url>)
```

发送到 `delivery.targets`：

```bash
lark-cli im +messages-send --chat-id "<chat_id>" --markdown "$(cat progress_message.md)" --as bot
lark-cli im +messages-send --user-id "<open_id>" --markdown "$(cat progress_message.md)" --as bot
```

`im +messages-send --markdown` 不支持 `@file`，必须用 `$(cat file)`。

## Output

最终回复用户：

```text
进度文档: <doc_url>
已投递: <target.name>, ...
统计范围: <since> ~ <until>
数据来源: <repo list>
```

如有采集、权限或投递失败，列出失败点。

## Key Rules

1. 这是进度同步，不是周报；重点是“现在进展到哪里、接下来做什么”。
2. GitHub 采集默认包含所有分支，除非用户明确要求只看默认分支。
3. 用户提到具体 PR 时必须使用 PR 模式；不要用最近 N 天近似替代。
4. 不要把未合并分支或打开 PR 写成“已上线”或“已合并”。
5. 0 数据时不要编造，输出“该范围内未匹配到团队成员代码改动”，并建议检查仓库配置、GitHub 用户映射或时间范围。
6. 飞书文档创建后必须自动 transfer owner，并重新授权 bot；权限命令必须带 `--yes`。
7. 飞书文档和消息投递使用 bot 身份。
8. 群消息面向团队协作，不面向代码审计；把可追溯证据放进文档，不要把第一屏写成提交清单。
