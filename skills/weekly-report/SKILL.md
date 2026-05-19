---
name: commit-weekly-report
description: 从 GitHub（可选 GitLab）收集团队 commit 数据，生成周报，通过 lark-cli 创建飞书文档并自动转移文档权限。当用户说"生成周报"、"这周大家做了什么"、"commit summary"、"team weekly report" 等类似请求时触发。
---

# Commit Weekly Report (CC / Codex)

> 本 Skill 完全基于 `lark-cli` + `python3` + 标准 shell 工具，
> 可在任何安装了 Claude Code 或 Codex 的环境中使用。
> 采用 **subagent 并行采集 + 主 agent 汇总** 架构，避免上下文溢出。

## Prerequisites

| 依赖 | 验证命令 |
|---|---|
| lark-cli | `lark-cli auth status` |
| python3 | `python3 --version` |
| GitHub token | `gh auth token` 或环境变量 `GITHUB_TOKEN` |
| GitLab token（可选，自建 GitLab） | 环境变量 `GITLAB_TOKEN` 或 config.yaml |

## Execution Flow

### Step 1: 读取配置

读取 `skills/weekly-report/config.yaml`，获取：

- `team.members` — 团队成员列表、用户名、extra_emails
- `gitlab` — GitLab 连接信息
- `github` — GitHub 仓库列表（可选）
- `lark.permissions` — 飞书文档权限配置
- `report` — 报告生成选项

Token 优先级：
1. 环境变量 `GITHUB_TOKEN` / `GITLAB_TOKEN`
2. config.yaml 中的 `github.token` / `gitlab.token`
3. GitHub 还可用 `gh auth token`

计算日期范围（`since` / `until`）：
- "本周" / "这周" / "周报" → 最近 7 天（今天往前推 7 天 ~ 今天）
- "上周" → 上周一 ~ 上周日
- "最近 N 天" → N 天前 ~ 今天
- 未指定 → **默认最近 7 天**

> 注意：周报覆盖完整 7 天，不跳过周末。

从各成员的 `extra_emails` 字段构造 `--extra-emails` 参数：
格式 `user1=email1;email2,user2=email3`（多邮箱 `;` 分隔，多用户 `,` 分隔）。

### Step 2: 并行采集每位成员的 Commit 数据

**使用 Agent 工具为每位成员 spawn 一个 subagent**，所有 subagent 并行执行。

每个 subagent 的任务：

1. 运行 `summarize.py` 获取该成员的原始数据：

```bash
python3 skills/weekly-report/scripts/summarize.py \
  --gitlab-url "<gitlab.base_url>" \
  --token "<gitlab_token>" \
  --users "<该成员 username>" \
  --since "<YYYY-MM-DD>" \
  --until "<YYYY-MM-DD>" \
  --output /tmp/weekly_<username>.md \
  --no-header \
  --github-repos "<github.repos，逗号分隔>" \
  --github-token "<github_token>" \
  --github-users "<该成员的 gitlab_to_github 映射>" \
  --extra-emails "<该成员的 extra_emails>"
```

2. 读取 `/tmp/weekly_<username>.md`，撰写该成员的**精炼分析摘要**（300-500 字），包含：
   - 提交数、代码变更量（+X / -X）
   - 活跃项目列表
   - 本周重点工作（按项目/模块分组，2-4 条）
   - 已合并 / 进行中的 MR 链接
   - 一句话概括

3. 将精炼摘要写入 `/tmp/weekly_summary_<username>.md`

4. 返回摘要内容给主 Agent

**Subagent prompt 模板：**

```
你是周报采集 agent，负责收集 <display_name>(@<username>) 的 commit 数据并生成分析摘要。

1. 执行以下命令获取原始数据：
   python3 skills/weekly-report/scripts/summarize.py \
     --gitlab-url "<gitlab.base_url>" --token "<token>" \
     --users "<username>" --since "<since>" --until "<until>" \
     --output /tmp/weekly_<username>.md \
     [--github-repos "..." --github-token "..." --github-users "..."] \
     [--extra-emails "..."]

2. 读取 /tmp/weekly_<username>.md

3. 写一份精炼分析摘要到 /tmp/weekly_summary_<username>.md，格式如下：

### <display_name> (@<username>) — X commits, +X / -X
**本周重点：一句话概括**
1. **工作条目 1**（项目名，N commits, +X/-X）
   - 具体描述
   - MR: [!123](url) 已合并/进行中
2. **工作条目 2** ...

**MR/PR 汇总：**
- 已合并: [!123](url) 标题, ...
- 进行中: [!456](url) 标题, ...

摘要要求：
- 所有数据必须来自原始输出，禁止编造
- 保留 MR/PR 链接作为关键证据
- 统计数据（commit 数、+/-行数）必须精确
- 具体 commit 链接不用列，原始数据文档里有完整记录

4. 返回摘要内容。
```

### Step 3: 获取 OKR 上下文（可选）

如果 `okr.enabled` 为 true：

使用 `lark-cli docs +fetch` 或 MCP 工具读取 OKR 文档内容：

```bash
lark-cli docs +fetch --url "<okr.doc_url>" --as bot
```

提取当前 OKR 周期的目标（O）和关键结果（KR），作为 Step 4 分析报告的上下文。

### Step 4: 汇总分析报告

等所有数据采集完成后，读取各成员的原始数据（或 subagent 返回的摘要）。

基于数据，组装完整周报，写入 `/tmp/weekly_analysis.md`：

```markdown
# 团队周报 (MM.DD — MM.DD)

## 本周总览
| 指标 | 数据 |
|---|---|
| 活跃成员 | X 人 |
| 总提交 | X 次 |
| 合并请求 | X 个 |
| 代码变更 | +X / -X 行 |

## 项目维度概览
| 项目 | 提交数 | 代码变更 | 参与人 |
|---|---|---|---|
| ... | ... | ... | ... |

## 个人工作总结
（按提交数降序排列，包含 MR 链接）

## 本周关键进展
1. 3-5 条核心成果

## OKR 进展映射
（仅在 okr.enabled 时生成此节）

| OKR 目标 | 本周相关工作 | 贡献人 |
|---|---|---|
| O1: ... | 具体工作条目，引用 MR 链接 | @username |
| O2: ... | ... | ... |

> 关联说明：基于 commit 内容和 MR 标题，将本周工作映射到 OKR 目标。
> 未能明确关联到 OKR 的工作列在"其他工作"中。

## 待关注事项
- 需推进的 MR、潜在风险等
```

将各成员的原始数据文件合并（完整 commit 链接、MR/PR 详情都在里面）：
```bash
# 按 config 中 members 顺序逐个列出，不用 glob 以免混入 summary 文件
cat /tmp/weekly_user1.md /tmp/weekly_user2.md /tmp/weekly_user3.md > /tmp/weekly_raw_all.md
```

### Step 5: 创建飞书文档

> **注意**：`lark-cli docs +create` 的 `@file` 路径必须是**相对于当前工作目录**的相对路径，
> 不支持绝对路径。需要先将文件 cp 到工作目录，或 cd 到文件所在目录。

**4a. 创建原始数据文档**（如果 `report.create_raw_data_doc` 为 true）：

```bash
cp /tmp/weekly_raw_all.md ./weekly_raw_all.md
lark-cli docs +create \
  --title "团队周报-原始数据 (MM.DD — MM.DD)" \
  --markdown @weekly_raw_all.md \
  --as bot
```

**4b. 创建汇总分析文档**（如果 `report.create_analysis_doc` 为 true）：

```bash
cp /tmp/weekly_analysis.md ./weekly_analysis.md
lark-cli docs +create \
  --title "团队周报-汇总分析 (MM.DD — MM.DD)" \
  --markdown @weekly_analysis.md \
  --as bot
```

从输出 JSON 中提取 `doc_id`（路径: `.data.doc_id`）。
文档 URL：输出中的 `.data.doc_url`。

### Step 6: 转移文档权限

对每个创建的文档，读取 `lark.permissions` 配置，依次执行：

**5a. 转移所有权**（给第一个 `doc_owner_open_ids`）：

```bash
lark-cli drive permission.members transfer_owner \
  --params '{"token":"<document_id>","type":"docx","stay_put":"<stay_put>","remove_old_owner":"<remove_old_owner>","old_owner_perm":"<old_owner_perm>","need_notification":"false"}' \
  --data '{"member_type":"<member_type>","member_id":"<第一个 doc_owner_open_ids>"}' \
  --as bot
```

**5b. 重新授权 Bot**：

```bash
lark-cli drive permission.members create \
  --params '{"token":"<document_id>","type":"docx","need_notification":"false"}' \
  --data '{"member_type":"openid","member_id":"<bot_open_id>","perm":"full_access"}' \
  --as bot
```

**5c. 授权其余成员**（如有多个 `doc_owner_open_ids`）：

```bash
lark-cli drive permission.members create \
  --params '{"token":"<document_id>","type":"docx","need_notification":"false"}' \
  --data '{"member_type":"<member_type>","member_id":"<open_id>","perm":"full_access"}' \
  --as bot
```

> 权限操作失败时记录错误，不中断流程。

### Step 7: 消息投递

如果 `delivery.enabled` 为 true，构造富消息并发送给 `delivery.targets` 中的每个目标。

**消息模板**（markdown 格式）：

```
**📋 团队周报 (MM.DD — MM.DD)**

---

**本周总览**
活跃 X 人 · X 次提交 · X 个 MR · +X / -X 行

---

**🔑 关键进展**
1. 第一条核心成果
2. 第二条...
3. ...

---

**📊 OKR 进展映射**（仅 okr.enabled 时包含）

**O1 ...**
· KR?: 相关工作描述

**O2 ...**
· KR?: 相关工作描述

---

**⚠️ 待关注**
· 待推进的 MR 和风险项

---

📝 [汇总分析文档](<analysis_doc_url>) · 📊 [原始数据文档](<raw_doc_url>)
```

**发送命令**：

先将消息内容写入临时文件 `weekly_message.md`，然后通过 `$(cat)` 传递：

对 type=user 的目标：
```bash
lark-cli im +messages-send --user-id "<id>" --markdown "$(cat weekly_message.md)" --as bot
```

对 type=chat 的目标：
```bash
lark-cli im +messages-send --chat-id "<id>" --markdown "$(cat weekly_message.md)" --as bot
```

> **注意**：`im +messages-send` 的 `--markdown` 不支持 `@file` 语法，必须用 `$(cat file)` 传递内容。
> 投递失败时记录错误，不中断流程。

### Step 8: 输出结果

```
📊 原始数据文档: <raw_doc_url>
📝 汇总分析文档: <analysis_doc_url>
📨 已投递: <target.name>, ...
```

如有权限操作或投递失败，一并报告。

---

## Key Rules

1. **必须使用 subagent 并行采集**，禁止在主 Agent 中一次性处理所有成员的原始数据
2. **禁止**手写 Python 脚本 — 使用已有的 `summarize.py`
3. **禁止**跳过任何团队成员
4. **严禁编造**：汇总报告和消息中的每一条数据、每一个项目名、每一个 MR 链接都必须在原始数据文件中有明确来源。原始数据中没有的内容绝对不能出现在报告里
5. **每个文档创建后必须执行权限转移**
6. 所有 `lark-cli` 命令使用 `--as bot` 身份执行
7. 大文件内容使用 `@file` 传递给 lark-cli，不要通过命令行参数传递
8. Subagent 返回的摘要应在 300-500 字，包含关键数据和 MR 链接

## Troubleshooting

| 问题 | 解决 |
|---|---|
| `lark-cli: not configured` | `echo "<secret>" \| lark-cli config init --app-id "<id>" --app-secret-stdin --brand feishu` |
| 权限转移失败 | 检查飞书应用权限是否包含 `drive:drive` 和 `docs:permission.member:transfer` |
| summarize.py 超时 | 缩小日期范围或增加 `--timeout 60` |
| `@file` 报错 | 确认文件路径正确且文件存在 |
| 文档创建成功但无法打开 | 检查 `doc_owner_open_ids` 是否正确 |
| subagent 返回空数据 | 该成员本周无提交，在报告中标注"本周无新提交" |
