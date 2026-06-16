# Lark Skills

基于 lark-cli 的飞书/Lark 自动化任务集合，兼容 Codex / Claude Code 等 AI 编码代理。

## 任务结构

每个任务定义在 `skills/<name>/SKILL.md`，包含完整的执行步骤。
配置文件为同目录下的 `config.yaml`（从 `config.example.yaml` 复制并填入真实值）。

可用任务：
- `skills/lark-doc-personal/SKILL.md` — 个人版：user 身份一步到位创建文档到个人云空间
- `skills/lark-doc-deliver/SKILL.md` — 企业版：bot 创建 + 权限转移 + 消息投递（可被其他 Skill 调用）
- `skills/doc-summary/SKILL.md` — 飞书文档搜索 + 汇总（调用 lark-doc-deliver 完成投递）
- `skills/weekly-report/SKILL.md` — 团队周报生成
- `skills/progress-report/SKILL.md` — 代码进度同步：按最近代码改动、分支和 PR 生成进度文档并投递

执行任务时，读取对应 SKILL.md 并按步骤执行。

## lark-cli 使用要点

- 大内容传递用 `@file`（相对路径）：`lark-cli docs +create --markdown @report.md`
- `im +messages-send` 的 `--markdown` 不支持 `@file`，用 `$(cat file)` 传递
- 原始 API 调用：`lark-cli api <METHOD> <path> --data '<json>' --as <bot|user>`
- 分页：`--page-all --page-size 50`

## 飞书 API 身份策略

- **文档搜索**（`doc-summary`）：`--as user`（搜索 API 仅支持 user_access_token）
- **企业版文档创建 / 权限管理 / 消息投递**（`lark-doc-deliver`、`weekly-report`、`progress-report`）：`--as bot`
- **个人版文档创建**（`lark-doc-personal`）：必须 `--as user`；bot 创建的文档会落在 app 云空间，跨空间 move/transfer 在个人版不可行

## 开发规范

- 新任务复制现有结构，保持 SKILL.md 可独立执行
- config.yaml 含敏感信息，只提交 config.example.yaml
- 所有报告数据必须有原始来源，严禁编造
