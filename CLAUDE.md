# Lark Skills

基于 Claude Code + lark-cli 的飞书/Lark 自动化 Skill 集合。

## 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| Agent 框架 | Claude Code (CC) | Skill / subagent 原生支持，定时任务可通过 launchd + `claude -p` 触发 |
| 飞书集成 | `lark-cli`（CLI） | 纯命令行调用，不依赖 SDK / 运行时；适合 Agent 直接操作 |
| 数据采集 | python3 脚本 | 处理 GitHub/GitLab API 分页、并发、格式化 |
| 配置管理 | YAML (`config.yaml`) | 每个 skill 独立配置，真实值 gitignore，模板提交 |

## 架构约定

### Skill 结构

分为两类：**通用能力 Skill** 和 **场景 Skill**。

**通用能力 Skill**（可被其他 Skill 调用）：

```
skills/lark-doc-deliver/        # 飞书企业版：bot 创建 + 权限转移 + 消息投递
├── SKILL.md
├── config.yaml
└── config.example.yaml

skills/lark-doc-personal/       # 飞书个人版：user 一步到位创建到个人云空间
├── SKILL.md
├── config.yaml
└── config.example.yaml
```

> 选哪一个：**面向组织内分发**（员工/群聊）用 `lark-doc-deliver`；**面向个人账号归档**用 `lark-doc-personal`。
> 两者背后是完全不同的飞书应用类型，配置和 API 调用流程互不兼容。

**场景 Skill**（面向具体业务场景，可调用通用能力 Skill）：

```
skills/doc-summary/             # 文档总结框架
├── SKILL.md
├── config.yaml                 # 主配置（指定当前场景，gitignored）
├── config.example.yaml
└── scenarios/                  # 场景预设
    └── example.yaml            # 模板；用户自己复制并改名（如 tech-design.yaml）

skills/weekly-report/           # 周报生成
├── SKILL.md
├── config.yaml
├── config.example.yaml
└── scripts/

skills/progress-report/         # 项目进度同步
├── SKILL.md
├── config.yaml
├── config.example.yaml
└── scripts/
```

对应入口：`.claude/commands/<skill-name>.md` — 轻量 wrapper，引用 SKILL.md。

### Skill 间调用

`doc-summary` 生成汇总报告后，调用 `lark-doc-deliver` 完成文档创建和消息投递。
调用方式：读取并执行 `skills/lark-doc-deliver/SKILL.md`，传入 markdown_file、title、message_file。

### 飞书 API 身份策略

按操作类型选择身份：
- **文档搜索**（`doc-summary`）：使用用户身份（`--as user`），因为搜索 API 仅支持 user_access_token。需一次性执行 `lark-cli auth login --domain docs` 授权
- **企业版文档创建 / 权限管理 / 消息投递**（`lark-doc-deliver`）：使用 bot（`--as bot`），由 `lark.identity` 配置控制
- **个人版文档创建**（`lark-doc-personal`）：必须用 `--as user`。个人版 bot 创建的文档会落在 app 云空间（用户 UI 不可见），且 `transfer_owner` + 跨空间 `drive +move` 在个人版不可行
- **weekly-report / progress-report**：使用 bot（`--as bot`），覆盖文档创建、权限管理、消息投递

### Subagent 并行模式

处理多成员数据时，为每位成员 spawn 独立 subagent 并行执行，避免主 Agent 上下文溢出。
Subagent 产出写入 `/tmp/` 临时文件，主 Agent 汇总。

### lark-cli 使用要点

- 大内容传递用 `@file`（相对路径）：`lark-cli docs +create --markdown @report.md`
- `im +messages-send` 的 `--markdown` 不支持 `@file`，用 `$(cat file)` 传递
- 原始 API 调用：`lark-cli api <METHOD> <path> --data '<json>' --as <bot|user>`
- 分页：`--page-all --page-size 50`

## 团队配置

团队成员、飞书权限等在各 skill 的 `config.yaml` 中维护。
成员 `open_id` 来源：通过群聊成员 API 查询（`im/v1/chats/:chat_id/members`）。

## 开发规范

- 新 skill 复制现有结构，保持 SKILL.md 可独立执行
- config.yaml 含敏感信息，只提交 config.example.yaml
- 所有报告数据必须有原始来源，严禁编造
