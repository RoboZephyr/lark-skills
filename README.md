# Office Assistant（办公助手）

基于 Claude Code + lark-cli 的办公自动化工具集。包含 4 个 Skill：

- **lark-doc-personal** — 飞书个人版：一步到位创建文档到个人云空间
- **lark-doc-deliver** — 飞书企业版：bot 创建 + 权限转移 + 群聊投递
- **doc-summary** — 按场景关键词扫描飞书文档并生成汇总
- **weekly-report** — 从 GitHub/GitLab 采集 commit 生成团队周报

## 快速安装

```bash
# 1. Clone 仓库
git clone https://github.com/RoboZephyr/office-assistant.git ~/workspace/office-assistant
cd ~/workspace/office-assistant

# 2. 一键安装（将 skills 注册为全局 Claude Code 命令）
./install.sh

# 3. 编辑各 skill 的 config.yaml，填入真实值
# 4. 在任意目录打开 Claude Code，直接使用 /doc-summary、/weekly-report 等
```

安装后无需 `cd` 到本仓库，在任意目录的 Claude Code 中都可使用已安装的 skill。

```bash
# 按需安装单个 skill
./install.sh lark-doc-deliver

# 查看可安装的 skills
./install.sh --list

# 检查依赖
./install.sh --check

# 卸载
./uninstall.sh
```

---

## 当前场景

### 📑 文档汇总（doc-summary）

通用飞书文档总结框架，支持场景化配置。内置「技术设计文档扫描」场景，可自定义其他场景。

**使用方式：** 在任意目录的 Claude Code 中输入 `/doc-summary`

**功能：**
- 按场景配置搜索飞书文档（关键词 + 翻页采集）
- 按团队成员过滤 + 标题语义判断筛选
- 生成汇总报告，调用 `lark-doc-deliver` 创建飞书文档并投递

**配置：**
1. 复制 `skills/doc-summary/config.example.yaml` 为 `config.yaml`
2. 复制 `skills/doc-summary/scenarios/example.yaml` 创建场景文件（如 `tech-design.yaml`）
3. 执行 `lark-cli auth login --domain docs` 完成用户授权

---

### 📤 飞书文档投递（lark-doc-deliver，企业版）

通用能力 Skill：接收 markdown 内容，**用企业版 bot 身份**创建飞书文档，转移权限给指定员工，发送消息通知到群聊。可被其他 Skill 调用。

**配置：** 复制 `skills/lark-doc-deliver/config.example.yaml` 为 `config.yaml`，填入飞书权限和投递目标。

---

### 📝 飞书文档创建（lark-doc-personal，个人版）

通用能力 Skill：**用 user 身份**一步到位把 markdown 创建到你的飞书个人云空间。比 `lark-doc-deliver` 简单很多，没有权限转移和消息投递。

**适用：** 飞书个人版账号，单一用户归档场景。

**配置：** 复制 `skills/lark-doc-personal/config.example.yaml` 为 `config.yaml`；首次用前跑 `lark-cli auth login --domain docs,drive`。

---

### 📊 团队周报（weekly-report）

自动从 GitHub（可选 GitLab）采集 commit 数据，生成周报，创建飞书文档，关联 OKR 并投递到群聊。

**使用方式：** 在任意目录的 Claude Code 中输入：
```
/weekly-report
/weekly-report 上周
/weekly-report 最近 14 天
```

**功能：**
- 并行采集团队成员 commit + MR 数据
- OKR 进展自动映射
- 飞书文档创建 + 权限转移
- 富消息投递到群聊/个人

**配置：** 复制 `skills/weekly-report/config.example.yaml` 为 `config.yaml`，填入真实值。

---

## 环境准备

```bash
# 1. 安装 lark-cli
npm install -g @larksuite/cli

# 2. 配置飞书凭据
echo "<app_secret>" | lark-cli config init --app-id "<app_id>" --app-secret-stdin --brand feishu

# 3. 验证
lark-cli auth status
```

---

## 定时任务（launchd）

### 安装定时任务

```bash
# 复制 plist 到 LaunchAgents
cp launchd/com.office-assistant.weekly-report.plist ~/Library/LaunchAgents/

# 加载（启用）
launchctl load ~/Library/LaunchAgents/com.office-assistant.weekly-report.plist
```

### 查看状态

```bash
# 列出任务（-: 未运行, 0: 上次成功, 非0: 上次失败）
launchctl list | grep office-assistant
```

输出格式：`PID  ExitCode  Label`
- `-  0  com.office-assistant.weekly-report` → 未在运行，上次成功
- `12345  -  com.office-assistant.weekly-report` → 正在运行，PID=12345

### 手动触发

```bash
# 立刻执行一次（不影响定时计划）
launchctl start com.office-assistant.weekly-report
```

### 查看日志

```bash
# 标准输出
cat /tmp/office-assistant-weekly-report.stdout.log

# 错误输出
cat /tmp/office-assistant-weekly-report.stderr.log

# 实时跟踪
tail -f /tmp/office-assistant-weekly-report.stdout.log
```

### 停用 / 卸载

```bash
# 停用（保留文件，下次登录不再自动加载）
launchctl unload ~/Library/LaunchAgents/com.office-assistant.weekly-report.plist

# 彻底删除
launchctl unload ~/Library/LaunchAgents/com.office-assistant.weekly-report.plist
rm ~/Library/LaunchAgents/com.office-assistant.weekly-report.plist
```

### 修改执行时间

编辑 `launchd/com.office-assistant.weekly-report.plist` 中的 `StartCalendarInterval`：

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
launchctl unload ~/Library/LaunchAgents/com.office-assistant.weekly-report.plist
cp launchd/com.office-assistant.weekly-report.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.office-assistant.weekly-report.plist
```

### 休眠行为

- 电脑休眠时**不会唤醒**执行
- 唤醒后如果发现错过了执行时间，会**立即补执行一次**

---

## 目录结构

```
office-assistant/
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
│   └── weekly-report/                 # 场景 Skill：团队周报
│       ├── SKILL.md
│       ├── config.example.yaml
│       └── scripts/
│           └── summarize.py
├── launchd/
│   └── com.office-assistant.weekly-report.plist
├── CLAUDE.md                          # Claude Code 项目指令
├── AGENTS.md                          # Codex 项目指令
├── .gitignore
└── README.md
```
