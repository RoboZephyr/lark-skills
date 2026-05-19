# Lark Skills

基于 lark-cli 的飞书/Lark 自动化任务集合，兼容 Codex / Claude Code 等 AI 编码代理。

## 任务结构

每个任务定义在 `skills/<name>/SKILL.md`，包含完整的执行步骤。
配置文件为同目录下的 `config.yaml`（从 `config.example.yaml` 复制并填入真实值）。

可用任务：
- `skills/lark-doc-deliver/SKILL.md` — 飞书文档创建 + 权限转移 + 消息投递（通用能力）
- `skills/doc-summary/SKILL.md` — 飞书文档搜索 + 汇总（调用 lark-doc-deliver 完成投递）
- `skills/weekly-report/SKILL.md` — 团队周报生成

执行任务时，读取对应 SKILL.md 并按步骤执行。

## lark-cli 使用要点

- 大内容传递用 `@file`（相对路径）：`lark-cli docs +create --markdown @report.md`
- `im +messages-send` 的 `--markdown` 不支持 `@file`，用 `$(cat file)` 传递
- 原始 API 调用：`lark-cli api <METHOD> <path> --data '<json>' --as <bot|user>`
- 分页：`--page-all --page-size 50`

## 飞书 API 身份策略

- **文档搜索**：`--as user`（搜索 API 仅支持 user_access_token）
- **文档创建 / 权限管理 / 消息投递**：`--as bot`

## 开发规范

- 新任务复制现有结构，保持 SKILL.md 可独立执行
- config.yaml 含敏感信息，只提交 config.example.yaml
- 所有报告数据必须有原始来源，严禁编造
