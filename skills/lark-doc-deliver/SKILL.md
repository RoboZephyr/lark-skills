---
name: lark-doc-deliver
description: 通用飞书文档创建、云盘分类归档、权限转移和消息投递。接收 markdown 文件和标题，把文档创建到指定云盘文件夹（无法分类时进入收件箱），转移所有权并发送通知。当其他 Skill 需要将内容发布到飞书时调用。
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
| `folder_key`（可选） | `storage.folders` 中的分类键；无法判断时省略 | `competitor_analysis` |
| `folder_token`（可选） | 显式目标文件夹 token，优先级高于 `folder_key`，且必须已登记在 `storage` 中 | `YOUR_TARGET_FOLDER_TOKEN` |

## Execution Flow

### Step 1: 读取配置

读取 `skills/lark-doc-deliver/config.yaml`，获取：

- `lark.permissions` — 文档权限配置（所有权转移、bot 授权）
- `lark.identity` — API 调用身份（默认 `bot`）
- `storage` — 云盘主目录、默认收件箱、分类文件夹映射和分类别名
- `delivery` — 消息投递配置（目标列表、是否启用）

如果调用方提供了 `config_override`，按以下规则合并：
- 仅识别 `lark`、`storage` 和 `delivery` 三个顶级字段
- 浅合并：override 中存在的顶级字段完整替换默认配置中的对应字段
- override 文件不存在或格式错误时，记录警告并使用默认配置继续执行

### Step 2: 解析并验证云盘目标

按以下优先级解析 `target_folder_token`：调用方传入的 `folder_token` → `storage.folders[folder_key]` → 业务专用规则 → 根据标题和用户要求匹配 `storage.folder_aliases` → `storage.default_folder_token`。

- `target_folder_token` 为空时停止，禁止回退到云盘根目录。
- `folder_key` 不存在时记录警告并进入 `storage.default_folder_token`，不要猜测其他目录。
- 已知工作流应显式传入 `folder_key`，不要只依赖标题关键词。
- 业务专用规则优先于通用别名：当前周执行计划、需求进度和产品闭环检查会资料进入 `weekly_demand_management`；旧式团队/技术周报、周报原始数据、汇总分析和历史会议记录进入 `reports`。即使前一类标题同时含有“产品”“需求”或“协作”，仍以 `weekly_demand_management` 为准。
- 团队与招聘目录采用平铺结构：候选人面试记录进入 `candidates`；招聘流程、招聘作业和其他团队管理资料进入 `team`。Agent、工具和自动化类技术资料进入 `engineering`。
- 具体业务短语优先于泛词：竞品分析进入 `competitor_analysis`，行业/产品研究进入 `research`，候选人面试进入 `candidates`，招聘流程/作业进入 `team`；不能因为标题同时含有“产品”或“工程”而判成歧义。
- `archive` 仅在用户/调用方明确要求归档，或显式传入该 `folder_key` / `folder_token` 时使用；新文档不得仅凭宽泛标题自动进入归档。
- 不再维护通用“产研协作”分类。只有“协作”“流程”“规范”等宽泛词且没有更明确分类时，进入 `storage.default_folder_token`。
- 用户明确说“归档到某分类”时，同时匹配分类键和别名；例如“竞品分析”命中 `competitor_analysis`。仅有一个明确命中时才分类；仍有歧义时进入收件箱。
- `folder_token` 必须等于 `storage.default_folder_token` 或 `storage.folders` 中的一个已登记值，且不能等于 `storage.root_folder_token`；未登记时停止，防止误写团队知识库、个人文档库根目录或其他云盘位置。
- 创建前以 `lark.identity` 读取目标文件夹；无权限时停止，不要改在其他位置创建。
- 团队知识库文档不走本流程，除非调用方明确要求创建团队知识库节点。

### Step 3: 创建飞书文档

```bash
# 将源文件复制到工作目录
cp <markdown_file> ./lark_deliver_temp.md

lark-cli docs +create \
  --title "<title>" \
  --content @lark_deliver_temp.md \
  --doc-format markdown \
  --parent-token "<target_folder_token>" \
  --as <lark.identity>
```

从输出 JSON 中提取：
- `doc_url`（优先路径: `.data.document.url`；兼容路径: `.data.doc_url` / `.data.url`）
- `document_id`（优先路径: `.data.document.document_id`；兼容路径: `.data.doc_id` / `.data.document_id`，用于权限操作）

清理临时文件：`rm -f ./lark_deliver_temp.md`

### Step 4: 自动权限转移

文档创建后必须先完成权限转移，再投递消息。不要并行执行权限转移和消息投递，避免群里收到不可访问的文档。

**4a. 转移所有权**（给第一个 `doc_owner_open_ids`）：

```bash
lark-cli drive permission.members transfer_owner \
  --params '{"token":"<document_id>","type":"docx","stay_put":"<stay_put>","remove_old_owner":"<remove_old_owner>","old_owner_perm":"<old_owner_perm>","need_notification":"false"}' \
  --data '{"member_type":"<member_type>","member_id":"<第一个 doc_owner_open_ids>"}' \
  --as bot \
  --yes
```

`stay_put` 必须为 `true`，确保转移所有权后文档仍留在目标文件夹。

**4b. 重新授权 Bot**：

```bash
lark-cli drive permission.members create \
  --params '{"token":"<document_id>","type":"docx","need_notification":"false"}' \
  --data '{"member_type":"openid","member_id":"<bot_open_id>","perm":"full_access"}' \
  --as bot \
  --yes
```

**4c. 授权其余成员**（如有多个 `doc_owner_open_ids`）：

```bash
lark-cli drive permission.members create \
  --params '{"token":"<document_id>","type":"docx","need_notification":"false"}' \
  --data '{"member_type":"<member_type>","member_id":"<open_id>","perm":"full_access"}' \
  --as bot \
  --yes
```

如果 `doc_owner_open_ids[0]` 或 `bot_open_id` 缺失，停止投递并报告配置缺失。
如果 owner transfer 失败，停止消息投递并报告失败；不要发送一个可能无法访问的文档链接。

**4d. 所有者与归档回读验证**：

```bash
lark-cli drive metas batch_query \
  --user-id-type open_id \
  --data '{"request_docs":[{"doc_token":"<document_id>","doc_type":"docx"}],"with_url":true}' \
  --as bot

lark-cli drive files list \
  --folder-token "<target_folder_token>" \
  --page-all --page-size 200 \
  --as bot
```

确认元数据中的 `owner_id` 等于第一个 `doc_owner_open_ids`，并确认目标文件夹清单中存在 `document_id`。任一不符时停止消息投递并报告验证失败；不要把“创建成功”当作“归档成功”。

### Step 5: 消息投递

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

### Step 6: 输出结果

返回以下信息供调用方使用：

```
doc_url: <doc_url>
document_id: <document_id>
delivered_to: <target.name>, ...
folder_token: <target_folder_token>
owner_id: <verified_owner_open_id>
errors: <如有失败，列出>
```

---

## Key Rules

1. **消息投递始终用 `--as bot`**，用户身份缺少 `im:message` scope
2. **权限转移始终用 `--as bot`**
3. **文档创建身份由 `lark.identity` 配置决定**（默认 `bot`，某些场景需要 `user`）
4. **`@file` 仅支持相对路径**：`lark-cli docs +create --content @file.md --doc-format markdown`，需先 cp 到工作目录
5. **`$(cat file)` 传递消息内容**：`im +messages-send --markdown` 不支持 `@file`
6. 文档创建后必须先 transfer owner，再投递消息；owner transfer 失败时停止投递
7. 临时文件用完即删
8. `transfer_owner` / `permission.members.create` 必须带 `--yes`，否则 lark-cli high-risk-write 网关会要求确认并导致自动流程失败
9. 禁止在云盘根目录创建；无法判断分类时必须使用 `storage.default_folder_token`（00_收件箱）
10. `stay_put` 必须为 `true`，且权限转移后必须回读所有者和目标文件夹验证
11. 当前周执行资料与历史周报必须分流：`weekly_demand_management` 放当前需求/周计划，`reports` 只放旧式团队/技术周报与历史会议记录

## Troubleshooting

| 问题 | 解决 |
|---|---|
| `lark-cli: not configured` | `echo "<secret>" \| lark-cli config init --app-id "<id>" --app-secret-stdin --brand feishu` |
| 权限转移失败 | 检查飞书应用权限是否包含 `drive:drive` 和 `docs:permission.member:transfer` |
| 权限操作报 `confirmation_required` | 命令缺少 `--yes` |
| `@file` 报错 | 确认文件路径是相对路径且文件存在 |
| 消息投递失败 `missing_scope` | 消息投递必须用 `--as bot` |
| 文档创建成功但无法打开 | 检查 `doc_owner_open_ids` 是否正确 |
