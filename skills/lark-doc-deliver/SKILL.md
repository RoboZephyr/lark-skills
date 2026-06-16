---
name: lark-doc-deliver
description: 通用飞书文档创建+权限转移+消息投递。接收 markdown 文件和标题，创建飞书文档、转移所有权、发送消息通知。当其他 Skill 需要将内容发布到飞书时，调用此 Skill 完成投递。
---

# Lark Doc Deliver (CC / Codex)

> 通用能力 Skill：接收 markdown 内容，创建飞书文档，转移文档权限，发送消息通知。
> 可被其他 Skill 调用，也可独立使用。

## Prerequisites

| 依赖 | 验证命令 |
|---|---|
| lark-cli | `lark-cli auth status` |

## Input

本 Skill 被调用时，需要以下输入（由调用方提供或通过命令参数传入）：

| 参数 | 说明 | 示例 |
|---|---|---|
| `markdown_file` | 要创建为飞书文档的 markdown 文件路径 | `/tmp/report.md` |
| `title` | 飞书文档标题 | `团队技术设计文档汇总 (01.11 — 04.11)` |
| `message_file`（可选） | 消息投递内容的 markdown 文件路径，不提供则用文档链接作为消息 | `/tmp/message.md` |
| `config_override`（可选） | 覆盖默认 config.yaml 的配置路径 | `skills/doc-summary/scenarios/tech-design.yaml` |

## Execution Flow

### Step 1: 读取配置

读取 `skills/lark-doc-deliver/config.yaml`，获取：

- `lark.permissions` — 文档权限配置（所有权转移、bot 授权）
- `lark.identity` — API 调用身份（默认 `bot`）
- `delivery` — 消息投递配置（目标列表、是否启用）

如果调用方提供了 `config_override`，按以下规则合并：
- 仅识别 `lark` 和 `delivery` 两个顶级字段
- 浅合并：override 中存在的顶级字段完整替换默认配置中的对应字段
- override 文件不存在或格式错误时，记录警告并使用默认配置继续执行

### Step 2: 创建飞书文档

```bash
# 将源文件复制到工作目录
cp <markdown_file> ./lark_deliver_temp.md

lark-cli docs +create \
  --title "<title>" \
  --markdown @lark_deliver_temp.md \
  --as <lark.identity>
```

从输出 JSON 中提取：
- `doc_url`（路径: `.data.doc_url`）
- `document_id`（优先路径: `.data.doc_id`；兼容路径: `.data.document.document_id` / `.data.document_id`，用于权限操作）

清理临时文件：`rm -f ./lark_deliver_temp.md`

### Step 3: 自动权限转移

文档创建后必须先完成权限转移，再投递消息。不要并行执行权限转移和消息投递，避免群里收到不可访问的文档。

**3a. 转移所有权**（给第一个 `doc_owner_open_ids`）：

```bash
lark-cli drive permission.members transfer_owner \
  --params '{"token":"<document_id>","type":"docx","stay_put":"<stay_put>","remove_old_owner":"<remove_old_owner>","old_owner_perm":"<old_owner_perm>","need_notification":"false"}' \
  --data '{"member_type":"<member_type>","member_id":"<第一个 doc_owner_open_ids>"}' \
  --as bot \
  --yes
```

**3b. 重新授权 Bot**：

```bash
lark-cli drive permission.members create \
  --params '{"token":"<document_id>","type":"docx","need_notification":"false"}' \
  --data '{"member_type":"openid","member_id":"<bot_open_id>","perm":"full_access"}' \
  --as bot \
  --yes
```

**3c. 授权其余成员**（如有多个 `doc_owner_open_ids`）：

```bash
lark-cli drive permission.members create \
  --params '{"token":"<document_id>","type":"docx","need_notification":"false"}' \
  --data '{"member_type":"<member_type>","member_id":"<open_id>","perm":"full_access"}' \
  --as bot \
  --yes
```

如果 `doc_owner_open_ids[0]` 或 `bot_open_id` 缺失，停止投递并报告配置缺失。
如果 owner transfer 失败，停止消息投递并报告失败；不要发送一个可能无法访问的文档链接。

### Step 4: 消息投递

如果 `delivery.enabled` 为 true：

**构造消息内容**：
- 如果调用方提供了 `message_file` 且文件存在，使用该文件内容
- 否则（未提供或文件不存在），构造默认消息：`**<title>**\n\n[查看文档](<doc_url>)`

将消息写入临时文件 `lark_deliver_message.md`。

**发送消息**（消息投递必须用 `--as bot`）：

对 `delivery.targets` 中每个目标：

```bash
# type=user
lark-cli im +messages-send --user-id "<id>" --markdown "$(cat lark_deliver_message.md)" --as bot

# type=chat
lark-cli im +messages-send --chat-id "<id>" --markdown "$(cat lark_deliver_message.md)" --as bot
```

> 投递失败时记录错误，不中断流程。

### Step 5: 输出结果

返回以下信息供调用方使用：

```
doc_url: <doc_url>
document_id: <document_id>
delivered_to: <target.name>, ...
errors: <如有失败，列出>
```

---

## Key Rules

1. **消息投递始终用 `--as bot`**，用户身份缺少 `im:message` scope
2. **权限转移始终用 `--as bot`**
3. **文档创建身份由 `lark.identity` 配置决定**（默认 `bot`，某些场景需要 `user`）
4. **`@file` 仅支持相对路径**：`lark-cli docs +create --markdown @file.md`，需先 cp 到工作目录
5. **`$(cat file)` 传递消息内容**：`im +messages-send --markdown` 不支持 `@file`
6. 文档创建后必须先 transfer owner，再投递消息；owner transfer 失败时停止投递
7. 临时文件用完即删
8. `transfer_owner` / `permission.members.create` 必须带 `--yes`，否则 lark-cli high-risk-write 网关会要求确认并导致自动流程失败

## Troubleshooting

| 问题 | 解决 |
|---|---|
| `lark-cli: not configured` | `echo "<secret>" \| lark-cli config init --app-id "<id>" --app-secret-stdin --brand feishu` |
| 权限转移失败 | 检查飞书应用权限是否包含 `drive:drive` 和 `docs:permission.member:transfer` |
| 权限操作报 `confirmation_required` | 命令缺少 `--yes` |
| `@file` 报错 | 确认文件路径是相对路径且文件存在 |
| 消息投递失败 `missing_scope` | 消息投递必须用 `--as bot` |
| 文档创建成功但无法打开 | 检查 `doc_owner_open_ids` 是否正确 |
