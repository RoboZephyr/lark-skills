---
name: meeting-action-sync
description: Extract action items, owners, open questions, decisions, and follow-up notes from Lark/Feishu meeting minutes, transcripts, documents, or local Markdown; calibrate the draft with the user; then optionally update a Lark/Feishu document, project documentation, issue tracker/backlog files, and/or a group message. Use when the user asks to 根据会议讨论分配任务, 从会议纪要整理 TODO, 提取开放问题, 整理会议后续事项, 把会议结论写入项目, 同步会议行动项到群里, or turn meeting notes into actionable project follow-up.
---

# Meeting Action Sync

把一次会议讨论转成可追踪的协作产物：先从会议纪要或逐字稿提取事实，再和用户校准行动项、负责人、开放问题和决策，最后按需同步到飞书文档、项目文档、backlog/issue 文件和可选群消息。

## Prerequisites

| 依赖 | 用途 |
|---|---|
| `lark-cli` | 读取妙记 / 文档、创建或更新飞书文档、可选发送群消息 |
| `rg` / `git` | 查项目文档规范、更新索引、检查 diff |
| 目标项目写权限 | 写入项目约定的 follow-up、TODO、open questions、decision log 或 backlog 位置 |

按任务需要读取对应 Lark skill：

- 妙记 / 逐字稿：`lark-minutes` 或 `lark-vc`
- 飞书文档创建 / 更新：`lark-doc`
- 群消息发送：`lark-im`
- 权限 / scope / keychain 问题：`lark-shared`

## Inputs

常见输入：

- 飞书妙记 URL、会议纪要 URL、文档 URL、逐字稿文件或本地 Markdown。
- 目标项目目录，例如 `/path/to/project`。
- 用户给出的术语修正、speaker 映射、负责人、删改项。
- 可选：要同步的群名、群 ID 或消息正文。

如果用户没有提供目标项目目录，只整理飞书文档或本地 Markdown；如果用户没有明确要求发群，不发送群消息。

## Workflow

### 1. 读取会议来源

1. 识别输入类型：minutes / note / docx / 本地 transcript。
2. 获取元数据：标题、时间、参会人、owner、URL。
3. 获取逐字稿或正文，保存一份本地工作稿，便于反复修订。
4. 保留来源锚点：时间戳、speaker、原始文档 URL 或本地文件路径。

不要只根据自动总结下结论；行动项、开放问题和决策必须能回到会议原文或用户后续反馈。

### 2. 初稿提取

从会议内容提取：

- 关键共识。
- 行动项候选：动作、负责人、目标、来源片段。
- 开放问题候选：还没拍板、需要决策或实验验证的问题。
- 决策记录候选：已经明确的结论、取舍和依据。
- 术语问题：同音误识别、模型误转写、专有名词。
- 负责人映射：Speaker N 到真实姓名。

初稿里明确区分：

- **行动项**：已有明确动作和 owner，可进入 TODO / plan / backlog。
- **开放问题**：尚未确定方案，需要继续定义、实验或拍板。
- **决策记录**：已经达成共识，需要让后续执行者知道的结论。
- **证据项**：只是样例或输入材料，不要误列为行动项。
- **会议安排**：复盘时间等除非用户要求，一般不列入工程任务。

### 3. 用户校准

把初稿给用户 review，主动收集：

- 术语修正，例如 `bit` 应为 `beat`。
- 人名修正，例如 Speaker 1 / 2 的真实姓名。
- TODO 删除、合并、拆分。
- owner 调整。
- 开放问题边界调整。
- 决策记录补充或降级为开放问题。
- 哪些内容只是证据，不是 TODO。

用户反馈优先级高于自动转写。每轮反馈后更新本地草稿，再继续下一步。

### 4. 项目文档边界规则

写入项目前先确定项目的文档体系。优先读取：

1. 目标项目 `AGENTS.md`
2. 目标项目 `CLAUDE.md` 或等价说明
3. docs、TODO、plan、backlog、open questions 或 decision log 目录下的 README 和现有样例

通用规则：

- 优先复用项目现有的文件类型和命名规范，不要强加新的目录结构。
- 如果项目没有单独的“开放问题”文档类型，用户确认后可以用 `Open Questions` 小节记录，但正文要解释清楚下一步是谁拍板或验证。
- 不要把同一个跨模块开放问题拆成多个互相矛盾的文件；保留一个 canonical entry，在多个索引里引用同一个 ID 或标题。
- 总索引和分模块索引都要同步，避免“飞书 4 个、项目看起来 5 个”的漂移。
- 文件名、标题、ID 和正文边界必须一致；不要留下旧标题或旧文件名。
- 开放问题不等于实现计划。已确定的实施步骤应进入 plan / backlog；开放问题只承接未决问题、验证项和决策出口。

### 5. 创建或更新飞书文档

用 `lark-doc` 创建或更新整理后的会议文档。

推荐结构：

```markdown
# <会议标题> - 会议纪要

## 元信息
## 术语与人名校准
## 一句话结论
## 已形成的共识
## 行动项
## 开放问题
## 决策记录
## 来源摘录
```

如果只是普通 Markdown 纪要，整篇重写可用 `docs +update --command overwrite --doc-format markdown --content @file`。如果文档已有图片、画板、评论或复杂 block，优先局部 `block_replace` / `str_replace`，避免破坏不可重建内容。

### 6. 写入项目仓库

进入目标项目目录后：

1. 检查 `git status --short`，不要覆盖用户已有改动。
2. 按项目规范创建或更新行动项、开放问题、决策记录或 backlog 文件。
3. 更新所有入口：
   - 独立 follow-up / open-question / decision 文件。
   - 分模块索引。
   - 总索引或项目状态索引。
   - 其他项目 README / modules 索引，如果现有规范要求。
4. 用 `rg` 检查旧名、旧 ID、旧边界是否残留。
5. 跑项目文档 schema 校验或最接近的验证命令。

对跨目录写入或沙箱外项目写入，按环境要求请求权限；不要用绕过手段。

### 7. 可选群同步

只有用户明确要求并确认内容后才发群消息。

发送前必须确认：

- 目标群或人。
- 发送身份：bot 或 user。
- 最终正文。

群消息应短，不列内部路径细节，除非用户要求。推荐格式：

```text
我根据 <日期> 的会议纪要整理了一版行动项和开放问题，并同步到了项目文档里。

这次收敛为 <N> 个开放问题：
1. <ID>：<标题>，负责人：<owner>

行动项：
1. <动作>，负责人：<owner>

飞书纪要文档：
<url>
```

## Quality Checks

完成前至少检查：

- 飞书文档里的行动项、开放问题和决策记录与项目文档一致。
- 总索引、分模块索引和独立条目数量不互相矛盾。
- 负责人、术语、speaker 映射符合用户最后一次反馈。
- `bit` / `beat`、人名、项目名等误识别已用 `rg` 检查。
- review/verify 等用户要求删除或暂缓的事项没有重新出现。
- 项目校验命令已通过；如未能运行，明确说明。

## Output

最终回复用户时给出：

- 飞书文档 URL。
- 写入的项目文件路径。
- 行动项、开放问题和决策记录数量。
- 校验结果。
- 是否已发群，以及 message id。

不要把所有过程细节都展开；只列用户需要复核的入口和残余风险。
