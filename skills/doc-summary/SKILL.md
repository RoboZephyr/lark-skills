---
name: doc-summary
description: 通用飞书文档总结框架。按场景配置搜索飞书文档，筛选后生成汇总报告，通过 lark-doc-deliver 创建文档并投递。当用户说"扫描文档"、"文档汇总"、"doc summary"等类似请求时触发。
---

# Doc Summary (CC / Codex)

> 通用文档总结框架：按场景配置搜索飞书文档，筛选出目标文档，生成汇总报告，
> 最终调用 `lark-doc-deliver` Skill 完成文档创建和消息投递。
>
> 技术设计文档扫描只是本框架的一个场景预设。

## Prerequisites

| 依赖 | 验证命令 |
|---|---|
| lark-cli | `lark-cli auth status` |
| 用户登录 | `lark-cli auth login --domain docs`（一次性授权，token 自动刷新） |

> **本 Skill 使用用户身份（`--as user`）搜索和读取文档**，搜索结果基于登录用户的可见范围。

## Execution Flow

### Step 1: 加载场景配置

读取 `skills/doc-summary/config.yaml`，获取当前使用的场景名。

然后读取对应场景文件 `skills/doc-summary/scenarios/<scenario>.yaml`，获取：

- `scenario.name` — 场景名称
- `scenario.description` — 场景描述
- `team.members` — 要扫描的成员列表（display_name + open_id）
- `search.keywords` — 搜索关键词列表
- `search.time_range_days` — 时间范围
- `search.page_size` — 每页返回数量
- `filter.exclude_patterns` — 标题排除模式列表
- `filter.include_semantic` — 语义包含描述（什么样的文档应该保留）
- `filter.exclude_semantic` — 语义排除描述（什么样的文档应该排除）
- `report` — 报告格式配置
- `delivery` — 投递配置覆盖（可选，覆盖 lark-doc-deliver 默认配置）

计算时间范围：当前日期往前推 `time_range_days` 天。

### Step 2: 全局搜索 + 翻页采集

> **已知限制**：飞书 Search V2 API 的 `owner_ids` 过滤在 user_access_token 模式下不生效。
> 因此采用**全局搜索 + 按 owner_name 后过滤**的策略。

对 `search.keywords` 中每个关键词：

```bash
lark-cli docs +search --query "<keyword>" --page-size <page_size> --as user
# 翻页：用返回的 page_token 继续，最多 10 页/关键词
lark-cli docs +search --query "<keyword>" --page-size <page_size> --as user --page-token "<token>"
```

从每页返回的 `.data.results` 中提取文档信息，**后过滤条件**：
- `owner_name` 在团队成员列表中
- `create_time_iso` 在时间范围内

所有关键词结果按 `token`（doc_id）去重。

### Step 3: 文档筛选

对候选文档进行两轮筛选：

**第一轮：格式排除**

按 `filter.exclude_patterns` 中的正则/关键词排除。典型排除项（可在场景中自定义）：
- 智能纪要、文字记录（自动生成的会议记录）
- 周报、日报、周会记录
- 工作汇报、述职报告

**第二轮：语义判断**

基于 `filter.include_semantic` 和 `filter.exclude_semantic` 的描述，对剩余候选文档的标题进行语义判断。

> **原则**：宁可多收不漏。标题不确定时，读取文档内容前 2000 字辅助判断。

```bash
lark-cli docs +fetch --url "<doc_url>" --as user
```

### Step 4: 生成汇总报告

按 `report.format` 配置组装汇总报告，写入 `/tmp/doc_summary_report.md`。

默认格式：

```markdown
# <scenario.name> (MM.DD — MM.DD)

> 扫描范围：最近 N 天（MM.DD — MM.DD）
> 扫描成员：N 人
> 发现文档：N 篇

## 按成员分组

### 成员名 (N 篇)

| 文档 | 创建时间 |
|---|---|
| [标题](url) | YYYY-MM-DD |

...

## 统计

| 成员 | 文档数 |
|---|---|
| ... | ... |
| **合计** | **N** |
```

### Step 5: 构造投递消息

生成消息内容，写入 `/tmp/doc_summary_message.md`：

```markdown
**<scenario.name> (MM.DD — MM.DD)**

---

扫描 N 人 · 发现 N 篇文档

---

**按成员：**
· **成员名** (N 篇): [标题1](url), [标题2](url), ...
· ...

---

[完整汇总文档](<doc_url>)
```

### Step 6: 调用 lark-doc-deliver 完成投递

读取并执行 `skills/lark-doc-deliver/SKILL.md`，传入：

- `markdown_file`: `/tmp/doc_summary_report.md`
- `title`: `<scenario.name> (MM.DD — MM.DD)`
- `message_file`: `/tmp/doc_summary_message.md`

如果场景配置中有 `delivery` 字段，将场景 yaml 文件路径作为 `config_override` 传入。

> lark-doc-deliver 负责：创建飞书文档 → 权限转移 → 消息投递。
> 文档创建身份由 `lark-doc-deliver/config.yaml` 的 `lark.identity` 决定，本 Skill 不控制。

### Step 7: 输出结果

```
文档: <doc_url>
已投递: <target.name>, ...
```

清理临时文件：`rm -f /tmp/doc_summary_report.md /tmp/doc_summary_message.md`

---

## Key Rules

1. **搜索用 `--as user`**，需要用户身份才能访问文档搜索 API
2. **全局搜索 + 后过滤**：`owner_ids` API 过滤不生效，必须翻页采集后按 `owner_name` 过滤
3. **每个关键词最多翻 10 页**（200 条），避免 API 调用过多
4. **筛选以标题语义判断为主**，参考场景配置的 `include_semantic` / `exclude_semantic`
5. **严禁编造**：汇总报告中的每篇文档都必须有搜索 API 返回的原始记录
6. 文档创建和消息投递**委托给 lark-doc-deliver**，不在本 Skill 中直接操作
7. 搜索或读取某个文档失败时记录错误、跳过，不中断整体流程

## Troubleshooting

| 问题 | 解决 |
|---|---|
| `need_user_authorization` | 执行 `lark-cli auth login --domain docs` 重新授权 |
| token 过期 | lark-cli 自动刷新（refresh token 有效期 7 天），超期需重新登录 |
| 搜索结果少、漏检 | 在场景 yaml 的 keywords 中增加业务领域词 |
| `docs +fetch` 失败 | 文档未对你开放访问权限，跳过并在报告中标注 |
| 找不到场景文件 | 检查 config.yaml 的 `scenario` 字段和 `scenarios/` 目录 |
