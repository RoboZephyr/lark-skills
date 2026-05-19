---
name: lark-doc-personal
description: 飞书个人版文档创建。接收 markdown 文件和标题，用 user 身份一步到位创建到你的个人云空间根目录。当任务面向飞书个人版账号（非企业版）发布文档时使用。
---

# Lark Doc Personal

> 通用能力 Skill：用 `--as user` 在飞书个人版直接创建文档，归属当前登录用户的个人云空间。
> **不**做权限转移、不做消息投递、不依赖企业 bot —— 与企业版的 `lark-doc-deliver` 互不重叠。

## 为什么独立成一个 Skill

`lark-doc-deliver` 走的是 **企业版 bot 流程**：bot 创建 → transfer_owner 给员工 → bot 群发消息。
个人版没有"组织内员工"概念，bot 创建的文档会落在 app 云空间（用户 UI 不可见），
且 `stay_put=true` 后跨空间 move API（`drive +move`）会报 `1061002 params error`。
**最干净的方案就是 `--as user` 一步到位**，所以这里独立一个最小 Skill。

## Prerequisites

| 依赖 | 验证命令 | 期望 |
|---|---|---|
| lark-cli | `lark-cli --version` | 已安装 |
| 配置已初始化 | `lark-cli auth status` | 返回 `appId` |
| 已 OAuth 登录 | `lark-cli auth status` 输出含 `userOpenId` | 个人账号已授权 |

如未登录，跑：
```bash
lark-cli auth login --domain docs,drive --no-wait --json
# 把返回的 verification_url 给用户，用户在浏览器输入 code 完成授权后：
lark-cli auth login --device-code <从上一步拿到的 device_code>
```

## Input

| 参数 | 说明 | 示例 |
|---|---|---|
| `markdown_file` | 要创建为飞书文档的本地 markdown 路径 | `/Users/zephyr/Downloads/audit.md` |
| `title` | 飞书文档标题 | `作品集审查报告 (2026-05-19)` |
| `folder_token`（可选） | 指定目标文件夹 token，缺省 = 个人云空间根目录 | `nodcnHv5fk6WFgJHnAMiq78ewuS` |

## Execution Flow

### Step 1: 检查登录状态

```bash
lark-cli auth status
```

确认输出含 `userOpenId`。如无，按 Prerequisites 引导用户走 OAuth。

### Step 2: 复制到工作目录（`@file` 仅支持相对路径）

```bash
cp <markdown_file> /tmp/lark_personal_temp.md
cd /tmp
```

### Step 3: 创建文档

```bash
lark-cli docs +create \
  --title "<title>" \
  --markdown @lark_personal_temp.md \
  --as user
```

从输出 JSON 提取：
- `doc_url`（路径：`.data.doc_url`）
- `doc_id`（路径：`.data.doc_id`）

### Step 4（可选）: 移动到指定文件夹

如果调用方提供了 `folder_token`：

```bash
lark-cli drive +move \
  --file-token <doc_id> \
  --type docx \
  --folder-token <folder_token> \
  --as user
```

### Step 5: 清理

```bash
rm -f /tmp/lark_personal_temp.md
```

### Step 6: 输出结果

```
doc_url: <doc_url>
doc_id: <doc_id>
owner: <userOpenId from auth status>
```

URL 形式可能是 `www.feishu.cn/docx/...`，实际也可用 `my.feishu.cn/docx/...` 打开（个人版默认 UI 域名）。
两个域名打开的是同一份文档。

---

## Key Rules

1. **始终用 `--as user`** —— 个人版用 bot 创建会进 app 云空间（用户不可见），且 transfer + 跨空间 move 都不可行
2. **`@file` 仅支持相对路径** —— 一定要 `cp` 到 `/tmp` 后 `cd /tmp` 再调用
3. **不要套用 `lark-doc-deliver` 的 transfer_owner 流程** —— 个人版 user 创建的文档默认就在用户云空间，无需转移
4. **不发消息** —— 个人版 user_access_token 没有 bot 的 `im:message` 群发能力；如需通知用户，直接把 URL 给他

## Troubleshooting

| 现象 | 排查 |
|---|---|
| `missing required scope` | 重跑 `lark-cli auth login --domain docs,drive --no-wait --json` 走 OAuth 加 scope |
| 创建成功但用户 UI 看不到 | 大概率是误用了 `--as bot`，文档落在 app 云空间。重新用 `--as user` 创建即可，老文档用 `--as bot --yes` 删 |
| `1061002 params error`（move 时） | 文档在 app 云空间，跨空间 move 不支持。改为 `--as user` 重建 |
| 域名困惑 | `www.feishu.cn` 和 `my.feishu.cn` 都能打开同一份文档，飞书个人版 UI 默认走 `my.feishu.cn` |

## 与 lark-doc-deliver 的差异

| 维度 | lark-doc-deliver（企业版） | lark-doc-personal（个人版） |
|---|---|---|
| 创建身份 | bot (`tenant_access_token`) | user (`user_access_token`) |
| 权限转移 | 转给 `doc_owner_open_ids` 中的员工 | 无需，user 创建即归属 |
| 消息投递 | bot 在群里/私聊发 markdown | 无（个人版不支持） |
| 适用场景 | 团队周报、技术评审等组织内分发 | 个人文档归档、面向单一用户的交付 |
| config 复杂度 | 高（bot openid、成员列表、群 id） | 低（仅 app_id/secret + OAuth）|
