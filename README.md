# Lark Skills

把多步 [lark-cli](https://github.com/larksuite/cli) 调用打包成 [Claude Code](https://claude.com/claude-code) 和 [Codex](https://github.com/openai/codex) 可以直接执行的 Skill。

每个 Skill 是一份 `SKILL.md` + `config.yaml`：前者告诉 Agent 怎么调 lark-cli，后者放飞书 open_id、群 chat_id 等真实值。

> English summary at the bottom.

## 包含的 Skill

| Skill | 做什么 |
|---|---|
| `lark-doc-personal` | 用 user 身份把 markdown 创建到个人云空间。**飞书个人版用这个。** |
| `lark-doc-deliver`  | 用 bot 创建 docx，转所有权给指定员工，发消息到群聊。**企业版多人协作场景。** |
| `doc-summary`       | 按场景配置（关键词 + 团队成员）搜飞书文档，汇总后调 `lark-doc-deliver` 发布 |
| `weekly-report`     | 从 GitHub（可选 GitLab）拉 commit，subagent 并行生成每人摘要，合并为周报 |
| `progress-report`   | 从最近代码改动、分支和 PR 生成项目进度同步，创建飞书文档并投递到群 |

如果只是想试跑一遍，推荐从 `lark-doc-personal` 开始 —— 只需要一个飞书个人版账号 + OAuth 一次。

## 安装

```bash
git clone https://github.com/RoboZephyr/lark-skills.git ~/workspace/lark-skills
cd ~/workspace/lark-skills
./install.sh                       # 自动检测 Claude Code / Codex
```

安装做了三件事：
1. 把每个 Skill 的入口写到 `~/.claude/commands/` 或 `~/.codex/instructions/`
2. 复制 `config.example.yaml` → `config.yaml`（**你需要打开填入真实值**）
3. 完成后任意目录下 `/lark-doc-personal`、`/weekly-report` 等命令都能用

```bash
./install.sh lark-doc-personal     # 只装一个
./install.sh --codex               # 只装到 Codex
./install.sh --list                # 列出所有 Skill
./install.sh --check               # 只检查依赖
./uninstall.sh                     # 卸载
```

---

## 环境准备

```bash
# 安装 lark-cli
npm install -g @larksuite/cli

# 配置飞书自建应用凭据（在 https://open.feishu.cn/app 创建一个应用）
echo "<app_secret>" | lark-cli config init --app-id "<app_id>" --app-secret-stdin --brand feishu

# 验证
lark-cli auth status
```

需要哪些 OAuth scope 取决于用哪个 Skill，各 `SKILL.md` 里列了清单。

---

## Skill 详情

### lark-doc-personal（飞书个人版）

OAuth user 身份创建文档到你的个人云空间。一次 `lark-cli auth login --domain docs,drive` 之后可重复使用。

```
/lark-doc-personal title="标题" markdown=/path/to/file.md
```

详见 [`skills/lark-doc-personal/SKILL.md`](skills/lark-doc-personal/SKILL.md)。

---

### lark-doc-deliver（飞书企业版）

接收 markdown，用 bot 身份创建 docx，转所有权给指定员工，发消息通知到群聊。可被其他 Skill 调用。

需要在飞书开放平台建一个企业自建应用，开通 `drive:drive`、`docs:permission.member:transfer`、`im:message` 等权限。

详见 [`skills/lark-doc-deliver/SKILL.md`](skills/lark-doc-deliver/SKILL.md)。

---

### doc-summary（按场景汇总文档）

按关键词和团队成员 open_id 在飞书云空间搜文档，过滤、合并后调 `lark-doc-deliver` 投递汇总。

场景在 `skills/doc-summary/scenarios/*.yaml`，关键词列表、过滤规则、汇总模板都可改。

```
/doc-summary
```

详见 [`skills/doc-summary/SKILL.md`](skills/doc-summary/SKILL.md) 和 [`scenarios/example.yaml`](skills/doc-summary/scenarios/example.yaml)。

---

### weekly-report（团队周报）

从 GitHub（可选 GitLab）拉指定团队成员在指定时间段的 commit + PR/MR，subagent 并行各人摘要，主 agent 合并为周报，可选关联 OKR。

```
/weekly-report                # 默认最近 7 天
/weekly-report 上周
/weekly-report 最近 14 天
```

可通过 `launchd/com.lark-skills.weekly-report.plist` 定时执行（见下方）。

详见 [`skills/weekly-report/SKILL.md`](skills/weekly-report/SKILL.md)。

---

### progress-report（项目进度同步）

从 GitHub 仓库的最近代码改动、所有分支 commit 和 PR 状态整理项目进度，输出“已完成 / 进行中 / 接下来 / 待确认”，创建飞书文档并投递。

```
/progress-report
/progress-report 今天
/progress-report 最近 3 天
```

默认继承 `weekly-report` 的仓库、成员和飞书投递配置。详见 [`skills/progress-report/SKILL.md`](skills/progress-report/SKILL.md)。

---

## 定时任务（launchd）

定时任务通过 `launchd/run-weekly-report.sh` 执行：先尝试 Claude Code；如果 Claude 订阅、组织权限或其他错误导致非 0 退出，会自动 fallback 到 `codex exec` 继续执行 `/weekly-report 上周` 等价流程。

如果 launchd 环境拿不到 GitHub token，可复制本地环境文件：

```bash
cp launchd/weekly-report.env.example launchd/weekly-report.env
```

然后按需设置 `WEEKLY_REPORT_GITHUB_USER`、`GITHUB_TOKEN`、`GH_TOKEN` 或二进制路径。`launchd/weekly-report.env` 会被 `.gitignore` 忽略，不要提交真实 token。

### 安装定时任务

```bash
# 复制 plist 到 LaunchAgents
cp launchd/com.lark-skills.weekly-report.plist ~/Library/LaunchAgents/

# 加载（启用）
launchctl load ~/Library/LaunchAgents/com.lark-skills.weekly-report.plist
```

### 查看状态

```bash
# 列出任务（-: 未运行, 0: 上次成功, 非0: 上次失败）
launchctl list | grep lark-skills
```

输出格式：`PID  ExitCode  Label`
- `-  0  com.lark-skills.weekly-report` → 未在运行，上次成功
- `12345  -  com.lark-skills.weekly-report` → 正在运行，PID=12345

### 手动触发

```bash
# 立刻执行一次（不影响定时计划）
launchctl start com.lark-skills.weekly-report
```

### 查看日志

```bash
# 标准输出
cat /tmp/lark-skills-weekly-report.stdout.log

# 错误输出
cat /tmp/lark-skills-weekly-report.stderr.log

# 实时跟踪
tail -f /tmp/lark-skills-weekly-report.stdout.log
```

### 停用 / 卸载

```bash
# 停用（保留文件，下次登录不再自动加载）
launchctl unload ~/Library/LaunchAgents/com.lark-skills.weekly-report.plist

# 彻底删除
launchctl unload ~/Library/LaunchAgents/com.lark-skills.weekly-report.plist
rm ~/Library/LaunchAgents/com.lark-skills.weekly-report.plist
```

### 修改执行时间

编辑 `launchd/com.lark-skills.weekly-report.plist` 中的 `StartCalendarInterval`：

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Weekday</key>
    <integer>5</integer>    <!-- 0=周日, 1=周一, ..., 5=周五 -->
    <key>Hour</key>
    <integer>11</integer>   <!-- 24小时制 -->
    <key>Minute</key>
    <integer>0</integer>
</dict>
```

改完后重新加载：
```bash
launchctl unload ~/Library/LaunchAgents/com.lark-skills.weekly-report.plist
cp launchd/com.lark-skills.weekly-report.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.lark-skills.weekly-report.plist
```

### 休眠行为

- 电脑休眠时**不会唤醒**执行
- 唤醒后如果发现错过了执行时间，会**立即补执行一次**

---

## 目录结构

```
lark-skills/
├── install.sh                         # 一键安装脚本
├── uninstall.sh                       # 卸载脚本
├── .claude/commands/                  # 项目级入口（开发用）
│   ├── doc-summary.md
│   ├── lark-doc-deliver.md
│   └── weekly-report.md
├── skills/
│   ├── doc-summary/                   # 场景 Skill：文档汇总框架
│   │   ├── SKILL.md
│   │   ├── config.example.yaml
│   │   └── scenarios/
│   │       └── example.yaml           # 场景模板（提交到 git）
│   ├── lark-doc-deliver/              # 通用能力 Skill：飞书文档投递
│   │   ├── SKILL.md
│   │   └── config.example.yaml
│   ├── progress-report/               # 场景 Skill：项目进度同步
│   │   ├── SKILL.md
│   │   ├── config.example.yaml
│   │   └── scripts/
│   └── weekly-report/                 # 场景 Skill：团队周报
│       ├── SKILL.md
│       ├── config.example.yaml
│       └── scripts/
│           └── summarize.py
├── launchd/
│   └── com.lark-skills.weekly-report.plist
├── CLAUDE.md                          # Claude Code 项目指令
├── AGENTS.md                          # Codex 项目指令
├── .gitignore
└── README.md
```

`skills/doc-summary/scenarios/` 缺一个 `lark-doc-personal/` 是因为它没有场景。

---

## English

Packages multi-step [lark-cli](https://github.com/larksuite/cli) flows as skills that [Claude Code](https://claude.com/claude-code) and [Codex](https://github.com/openai/codex) can run.

Each skill is a `SKILL.md` (tells the agent which lark-cli commands to call, in what order) plus a `config.yaml` (real values: open_ids, chat_ids, tokens — gitignored).

Included:
- **`lark-doc-personal`** — create docs in your personal Lark cloud space (OAuth user identity)
- **`lark-doc-deliver`** — bot creates docx, transfers ownership, sends chat message (enterprise app)
- **`doc-summary`** — search Lark docs by keywords + team open_ids, summarize, deliver
- **`weekly-report`** — pull commits from GitHub/GitLab, parallel per-member summarization, team report

Install:
```bash
git clone https://github.com/RoboZephyr/lark-skills.git
cd lark-skills && ./install.sh
```

Try `lark-doc-personal` first — it only needs a Lark personal account and one OAuth login.

MIT.
