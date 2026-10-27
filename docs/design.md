# Agent 使用体检报告（agent-usage-report）设计文档

> 状态：设计稿，待确认后开工
> 日期：2026-10-26
> 一句话：**脚本在本机数数，模型只负责解读和写报告**。给 Claude Code、Codex 等编程 Agent 的用户出一份“哪些用对了、哪些用错了、下一步改什么”的体检报告，外加一张能晒的分享卡，改完可以复测对比。

---

## 0. 目标与非目标

**目标**

1. 小白复制一段提示词给自己的 Agent，或者装一个 Skill，五分钟内拿到一份中文 HTML 体检报告。
2. 报告的每条结论都有本机统计数字撑腰，每条建议都能直接执行：一条命令、一段提示词，或者一处配置。
3. 同时体检“怎么用”（会话习惯）和“怎么配”（Skill、规则文件、MCP、权限）。
4. 一台机器上装了几个 Agent，就在一份报告里一起看。
5. 改完再跑一次，报告直接给出前后对比。
6. 附一张不含项目名和路径的分享卡。

**非目标**

- 不做代价统计面板（`/usage`、ccusage 这类工具已经做得很好）。
- 不替用户自动改配置。报告只给命令和提示词，由用户决定是否执行。
- 不上传任何数据，不调用任何远程接口（模型解读那一步由用户自己的 Agent 完成，与日常使用同一个账号）。
- 不评价“写的代码好不好”，只评价“Agent 用得好不好”。

---

## 1. 兼容哪些 Agent 产品

### 1.1 调研结论总表

“本机实测”指 2026-10-26 在作者 macOS 机器上只读检查的结果。

| 产品 | 会话记录位置（macOS / Linux） | Windows | 格式 | 稳定性 | 本机实测 |
|---|---|---|---|---|---|
| Claude Code（终端、桌面 App Code 标签、VS Code 插件） | `~/.claude/projects/<编码后的路径>/<session>.jsonl`；子代理在 `<session>/subagents/agent-*.jsonl` | `%USERPROFILE%\.claude\...` | JSONL，每行一条事件 | 中：字段持续增加，旧字段基本保留；30 天自动清理 | ✅ 25 个项目目录、409 个 jsonl、1.2 GB；版本 2.1.286–2.1.308 |
| OpenAI Codex（CLI、App、IDE 插件） | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`，**7 天后压缩成 `.jsonl.zst`**；另有 `state_5.sqlite`（会话列表）、`thread_history_1.sqlite`（逐条记录） | `%USERPROFILE%\.codex\...` | JSONL / zstd / SQLite | 低：存储层在快速演进（sqlite 编号已到 5、rollout 迁移表） | ✅ 51 个 jsonl + 918 个 zst、4.2 GB；sqlite 里 945 个会话 |
| Cursor（IDE / CLI） | 主库 `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`（`cursorDiskKV` 表，`composerData:*`、`bubbleId:*`）；副本 `~/.cursor/projects/<路径>/agent-transcripts/<id>/<id>.jsonl` | `%APPDATA%\Cursor\User\...`；Linux `~/.config/Cursor/User/...` | SQLite KV（内部格式）/ 不完整的 JSONL | 很低：内部格式，无公开文档 | ⚠️ transcripts 只有 role/message/type，**无时间戳、无模型、无 token** |
| Gemini CLI | `~/.gemini/tmp/<project_hash>/chats/`；手动保存在 `checkpoint-<tag>.json` | `%USERPROFILE%\.gemini\...` | JSON | 中：默认保留 30 天 | ❌ 本机未用（只有 Antigravity 的 `.pb`） |
| OpenCode | 新版 `~/.local/share/opencode/opencode.db`（`session_v2`、`session_message`）；旧版 `storage/session|message|part/*.json` | `%USERPROFILE%\.local\share\opencode` | SQLite（v2 schema）/ 旧 JSON | 低：v1→v2 改过表结构，社区工具已被搞坏过 | ✅ 33 个会话、8228 条消息，版本 2.0.20–2.1.2；session_v2 自带 token 和 cost 汇总 |
| pi（badlogic/pi-mono） | `~/.pi/agent/sessions/--<路径>--/<时间>_<id>.jsonl` | 同结构 | JSONL（有官方 session-format 文档，version 3，树形 id/parentId） | 中高：有公开格式文档和版本号 | ⚠️ 本机只有 `~/.pi/agent/skills`，没有会话 |
| Google Antigravity | `~/.gemini/antigravity/` | — | protobuf（`.pb`、`.pbtxt`） | 极低 | ❌ 不支持 |

**配置位置**

| 产品 | 规则文件 | Skill | MCP | 权限 / 沙箱 | 插件 / 其他 |
|---|---|---|---|---|---|
| Claude Code | `CLAUDE.md`（项目根、`~/.claude/`）、`CLAUDE.local.md`、`.claude/rules/*.md`；没有 CLAUDE.md 时读 `AGENTS.md` | `~/.claude/skills/`、`.claude/skills/`、插件内 `skills/` | `~/.claude.json`（个人）、`.mcp.json`（项目） | `settings.json` 的 `permissions`、`~/.claude.json` 里每个项目的 `allowedTools` | `~/.claude/plugins/installed_plugins.json`、`agents/*.md`、hooks 在 settings.json |
| Codex | `~/.codex/AGENTS.md`、项目逐级 `AGENTS.md` / `AGENTS.override.md`；上限由 `project_doc_max_bytes` 控制 | `~/.agents/skills`、`.agents/skills`（官方）；`~/.codex/skills`（旧位置，本机仍在用） | `config.toml` 的 `[mcp_servers.*]` | `approval_policy`、`sandbox_mode`、`~/.codex/rules/*.rules` | `[plugins]`、`[hooks]` 或 `hooks.json` |
| Cursor | `.cursor/rules/*.mdc`、`AGENTS.md`、用户规则（存在 App 里） | `~/.cursor/skills`、`.cursor/skills` | `~/.cursor/mcp.json`、`.cursor/mcp.json` | `~/.cursor/cli-config.json` 的 `permissions.allow/deny` | — |
| Gemini CLI | `GEMINI.md`（全局 `~/.gemini/`、项目逐级） | `~/.gemini/skills` | `settings.json` 的 `mcpServers` | `settings.json` | 扩展 |
| OpenCode | `AGENTS.md` | `~/.config/opencode/skills`，并兼容 `.claude/skills`、`.agents/skills` | `opencode.json` 的 `mcp` | `opencode.json` 的 `permission` | `plugin` |
| pi | `AGENTS.md`（`~/.pi/agent/`、父目录、当前目录） | `~/.pi/agent/skills`、`~/.agents/skills`、`.pi/skills` | 无内置 MCP | 无权限系统（默认 4 个工具） | 扩展 |

### 1.2 本机实测里踩到的坑（直接影响设计）

1. **子代理记录不在主文件里。** Claude Code 把子代理写进 `<session>/subagents/*.jsonl`。主文件里的 `Agent` 工具调用可以计次，但子代理花了多少 token，要去子目录里读。本机全部记录里有 155 次 `Agent` 调用、123 个子代理文件；但在 10-05 到 10-26 这三周里确实是 0，和前一份体检报告一致。**结论：统计窗口必须在报告里写明，不同窗口的结论可能相反。**
2. **权限模式同理。** 三周内全是 `auto`，全部历史里却有 549 条 `bypassPermissions`。所以窗口要默认固定（30 天），并在报告里写清楚。
3. **Codex 超过 7 天的记录会被压缩成 `.jsonl.zst`。** 只扫 `*.jsonl` 就会漏掉 95% 的会话（本机是 51 对 918）。Python 3.14 起标准库有 `compression.zstd`，更早的版本要靠系统的 `zstd` 命令；两样都没有时，改读 `state_5.sqlite` 拿会话级元数据（模型、审批模式、token 总数、首条消息），降级为“只有会话级指标”。
4. **Codex 的入口要靠字段区分。** `session_meta.originator`（如 `Codex Desktop`）和 `threads.source`（`vscode` / `exec` / 子代理）。子代理（`thread_spawn`）和 guardian 审查线程要单独计数，不能算成用户会话。
5. **Claude Code 入口靠 `entrypoint` 字段区分。** 本机只见到 `claude-desktop` 和 `claude-desktop-3p`（第三方模型提供商）；按文档，终端和 VS Code 也写在同一目录。
6. **Cursor 的 JSONL 只是导出副本。** 没有时间戳和模型，IDE 里的会话可能根本不在里面。真实数据在 `state.vscdb`，是未公开的内部格式（`composerData._v` 会变）。本机的 `~/.cursor/projects` 下还有大量 `.agent-data-cleanup-*` 目录，说明 Cursor 会主动清理。
7. **OpenCode 的 v1→v2 改过表结构。** 本机库里同时有新表 `session_v2` 和旧的 `storage/` JSON。必须先探测表名，再选解析器。
8. **Claude Code 记录默认只保留 30 天**（`cleanupPeriodDays`），桌面 App 的会话例外。报告只能看到“保留下来的”那部分，要在页头写明实际覆盖的起止日期。
9. **官方 `/insights` 的缓存就在 `~/.claude/usage-data/`**（`session-meta/*.json` 里有工具计数、打断次数、git 提交数；`facets/*.json` 是模型给每个会话打的目标和摩擦标签）。可以作为“可选加分数据源”，但不能依赖：它要用户先跑过 `/insights`，格式也没有文档。

### 1.3 第一版支持哪几个

| 级别 | 产品 | 理由 |
|---|---|---|
| **v1 正式支持** | Claude Code（三个入口合并统计，并按入口拆分） | 目标读者主体；格式最丰富；有完整官方最佳实践可对照 |
| **v1 正式支持** | Codex（CLI + App + IDE） | 第二大用户群；本机数据量最大；官方最佳实践成文 |
| v1.1 | OpenCode、pi | 开源，格式可查（pi 有正式格式文档，OpenCode 能读源码）；单个适配器预计 150 行左右 |
| v1.1 | Gemini CLI | JSON 格式简单，但作者本机无数据，需要找志愿者提供样本做测试夹具 |
| v1 只体检配置 | Cursor | 会话格式不可靠，先只查规则、Skill、MCP、权限；会话分析标“实验性”，放到 v2 |
| 不支持 | Antigravity 等 protobuf 格式 | 成本高、收益低 |

### 1.4 扩展口：适配器契约

每个产品写一个适配器文件 `collectors/<agent>.py`，只做三件事：

```python
class Collector:
    id = "claude_code"            # 唯一标识
    display_name = "Claude Code"

    def detect(self) -> Detection:
        """只看路径是否存在、粗算大小和版本，不读内容。返回 found / version / paths / size。"""

    def iter_events(self, since, until) -> Iterator[Event]:
        """把原始记录翻译成统一事件（见 4.3）。遇到不认识的行计入 unknown，不抛错。"""

    def read_config(self) -> ConfigSnapshot:
        """规则文件、Skill、MCP、权限、插件、hooks 的清单与体量（行数、字节），不读正文。"""
```

新增产品 = 新增一个适配器 + 一份测试夹具（脱敏的样例记录）+ 一份该产品的检查项清单（`checks/<agent>.yaml`）。指标引擎和报告模板不用改。

---

## 2. 用户需要什么样的报告

### 2.1 和官方工具的差异

官方已经有不少相关能力（来源见第 6 节），必须先划清边界：

| 官方能力 | 它做什么 | 我们不重复的部分 | 我们补上的部分 |
|---|---|---|---|
| `/insights` | 分析最近会话（单次最多 200 个），由模型给每个会话打标签，生成英文 HTML：你在做什么、怎么用、亮点、哪里出问题、可以试的功能、建议加进 CLAUDE.md 的内容、可复制的提示词、未来玩法 | 叙事式复盘、按项目归纳“你在做什么” | **逐项打分**；数字全部来自脚本，可复核；**跨 Agent**；**复测对比**；分享卡；中文、面向小白 |
| `/doctor` | 安装健康、未使用的 Skill / MCP / 插件及其上下文代价、CLAUDE.md 冗余、权限建议、`/usage` 推荐 | Claude Code 单产品的配置自动修复 | 把配置和**使用习惯**放在一起看；对 Codex 等其他产品做同类体检；修复交给用户，报告里直接引导用户去跑 `/doctor` |
| `/skill-doctor` | 每个 Skill 的上下文代价和调用次数，标出从未调用的 | Claude Code 的 Skill 明细 | 跨产品统计 Skill 安装与调用（同一个 Skill 装在 4 个目录里算一份），只给汇总和前 N 名 |
| `/usage`、`/stats` | 费用、套餐额度、7 天内按 Skill / 子代理 / MCP 拆分的消耗 + 建议 | 计费与额度 | 只用缓存命中率、模型分布这类“习惯信号”，不算钱 |
| `/fewer-permission-prompts` | 扫记录，生成只读命令白名单 | 生成白名单 | 只提示“你被权限弹窗打断过多少次”，然后让用户去跑它 |

**定位：`/insights` 是“医生写的病历”，我们是“体检单 + 复查单”。** 每一项都有指标、参考区间、判定和处方；下次再测，能看出哪一项变好了。报告里凡是官方已有工具能做的事，处方就直接写“去跑 `/doctor`”，不自己造。

### 2.2 报告结构（HTML 单文件）

```
① 页头       统计窗口（实际覆盖的起止日期）· 检测到的 Agent 与版本 · 数据完整度 · 生成时间
② 总评       总分 0–100 + 等级 + 一句话诊断（模型写）+ 三条“本周就改”
③ 四个分区，每区一张卡片墙（做对了 ✅ / 用错了 ⚠️ / 没用上 ⭕ / 数据不足 ➖）
      A 上下文管理    B 任务方法    C 配置卫生    D 效率与成本
   每张卡片 = 指标值 + 参考区间 + 判定 + 依据（官方文档链接）+ 处方（可复制）
④ 配置体检表   每个 Agent 一行：规则文件（有无 / 行数）· Skill（装了 / 用了）· MCP · 权限 · hooks
⑤ 跨 Agent 对比  同一指标在不同产品下的值；同一 Skill 装了几份
⑥ 复测对比     与上次结果的差值（第一次跑时隐藏）
⑦ 改进清单     按“省事程度 × 影响”排序的前 5 条处方，带复制按钮
⑧ 附录        统计口径、隐私说明、原始 facts.json 的位置
```

### 2.3 指标清单与打分规则

**通用约定**

- 每项判定为四档之一：`good` 做对了 / `bad` 用错了 / `unused` 没用上（功能可用，但计数为 0）/ `na` 数据不足（样本少于阈值，或该产品不记录这个信号）。
- 分数：good 计满分，unused 计 0.3，bad 计 0，na 不计入分母。每区按权重加总，总分 = 四区加权（A 30、B 30、C 20、D 20）。
- 阈值来自官方文档的明确数字，没有数字的就用“行为存在 / 不存在”判定，**不自己发明精确阈值**。需要经验阈值的项目标成“经验值”，并在附录里列出。
- 只在“会话数 ≥ 5 且用户消息 ≥ 30”时出总分；数据不够时只出卡片，不出分数。

**A. 上下文管理（Claude Code 依据：best-practices「Manage your session」「Avoid common failure patterns」）**

| ID | 指标 | 计算 | 判定 | 依据 |
|---|---|---|---|---|
| A1 | 清空 / 新开会话的习惯 | `/clear` 次数 + 每个会话的平均用户消息数 | 有 `/clear`，或中位会话 ≤ 20 条消息 → good；最长会话 > 40 条且 `/clear`=0 → bad | 「Use /clear frequently between tasks」；Cursor：切换任务时新开对话 |
| A2 | 自动压缩次数 | `compact_boundary` / Codex `compacted` 事件数 | 每 10 个会话 ≤ 1 次 → good；频繁 → bad | 「auto compaction」+「kitchen sink session」 |
| A3 | 主动压缩 | `/compact` 带不带说明 | 有带说明的 `/compact` → good；只有自动压缩 → unused | 「/compact <instructions>」 |
| A4 | 反复纠错 | 同一会话内连续 ≥ 3 条以否定词开头的短消息（“不对”“还是不行”“no”）（经验值） | 出现次数占会话比例 | 「corrected more than twice … run /clear」 |
| A5 | 子代理分流调研 | `Agent` / `Task` 调用次数；Codex `subAgentActivity`、`thread_spawn` | > 0 → good；0 且平均每会话读文件数 > 30 → unused | 「Use subagents for investigation」 |
| A6 | 旁路提问 | `/btw` 次数 | 0 → unused（不扣分太多） | 「/btw」 |

**B. 任务方法（依据：「Explore first, then plan」「Give Claude a way to verify」「Provide specific context」）**

| ID | 指标 | 计算 | 判定 | 依据 |
|---|---|---|---|---|
| B1 | Plan 模式 | `permissionMode=plan` 的轮次、`ExitPlanMode` 调用；Codex `collaboration_mode`=plan | 多文件改动的会话里用过 → good；0 → unused | 「Use plan mode」；Codex best practices「skipping planning」；Cursor「Plan first」 |
| B2 | 验证闭环 | 每个改了文件的会话里，是否出现测试 / 构建 / lint 命令或浏览器截图（命令正则 + 工具名） | ≥ 60% 的会话有 → good（经验值） | 「Give Claude a way to verify its work」；Codex「what done means」；Cursor「verifiable targets」 |
| B3 | 提示词具体度 | 用户消息长度中位数、含文件路径或 `@` 引用的比例、6 字以内短消息的比例 | 短消息比例高、引用比例低 → bad（经验值） | 「Provide specific context」「Reference files with @」 |
| B4 | 打断后纠偏 | 用户按 Esc 打断次数 / 会话；`/rewind` 次数 | 有打断也有 rewind → good；打断多、rewind 为 0 → unused | 「Course-correct early」「Rewind with checkpoints」 |
| B5 | 目标驱动 | `/goal` 次数；Codex `thread_goal_updated` | 长会话（> 20 条）里大量“继续”且 `/goal`=0 → unused | 「set the check as a /goal condition」 |
| B6 | 访谈式起步 | `AskUserQuestion` 调用次数 | > 0 → good | 「Let Claude interview you」 |
| B7 | 独立审查 | `/code-review`、审查子代理、Codex guardian 审查 | > 0 → good；0 → unused | 「Add an adversarial review step」 |

**C. 配置卫生（依据：「Write an effective CLAUDE.md」、costs「Move instructions from CLAUDE.md to skills」、skills 文档、Codex AGENTS.md 文档、Cursor rules 文档）**

| ID | 指标 | 计算 | 判定 | 依据 |
|---|---|---|---|---|
| C1 | 规则文件覆盖率 | 统计窗口内活跃项目中，有 CLAUDE.md / AGENTS.md / `.cursor/rules` 的比例；全局规则文件是否存在 | ≥ 50% → good；0 → bad | 「Run /init」；Codex「/init creates a starter」 |
| C2 | 规则文件长度 | 每份行数和字节数 | Claude Code ≤ 200 行 → good（官方数字）；Cursor 单条规则 ≤ 500 行（官方数字）；Codex 看 `project_doc_max_bytes` 是否会被截断 | costs「Aim to keep CLAUDE.md under 200 lines」；Cursor「Keep rules under 500 lines」；OpenAI harness 文章约 100 行 |
| C3 | Skill 装用比 | 去重后的 Skill 数（按 `name` 合并多个目录）vs 窗口内调用过的 Skill 数 | 调用率 < 10% 且装了 > 30 个 → bad（经验值） | skills「Every skill in the skill listing adds to your context on every turn」；Codex 技能列表上限为上下文的 2% |
| C4 | 重复安装 | 同名 Skill 出现在几个目录（`~/.claude/skills`、`~/.agents/skills`、`~/.codex/skills`、`~/.cursor/skills`、`~/.pi/agent/skills`…） | 仅提示，不扣分 | 各产品 skills 文档 |
| C5 | MCP 数量与使用 | 配置的服务器数 vs 窗口内调用过的服务器数 | 有配置但从未调用 → bad | costs「Disable unused servers」 |
| C6 | 权限设置 | 白名单条数；`bypassPermissions` / `danger-full-access` / `approval_policy=never` 的使用比例 | 长期完全放开 → bad（安全项）；有白名单或用 auto / sandbox → good | 「Configure permissions」；Codex `sandbox_mode` |
| C7 | Hooks | 是否配置了 hooks | 0 → unused | 「Use hooks for actions that must happen every time」 |
| C8 | 规则文件里的密钥 | 在规则文件里匹配 token / key 的模式（只计数，不输出内容） | 命中 → bad | Claude 目录文档「Plaintext storage」 |

**D. 效率与成本（依据：costs「Choose the right model」「Reduce token usage」、Codex best practices 关于 reasoning effort 的建议）**

| ID | 指标 | 计算 | 判定 | 依据 |
|---|---|---|---|---|
| D1 | 模型搭配 | 各模型的消息占比；短任务（≤ 3 轮）里最贵档模型的占比 | 只用最贵档 → bad；有分档 → good | 「Sonnet handles most coding tasks」；Codex「Low for well-scoped tasks」 |
| D2 | 缓存命中率 | cache_read / (cache_read + input + cache_creation) | ≥ 80% → good（经验值） | prompt caching 文档 |
| D3 | 意外中断 | API 错误、限流、上下文超限、App 退出后的续接次数 | 仅展示，不打分 | — |
| D4 | 并行与后台 | 并行会话（时间重叠）、worktree、后台任务 | > 0 → good；0 → unused | 「Run multiple Claude sessions」 |
| D5 | 用 CLI 代替 MCP | 常见服务（GitHub 等）是走 `gh` 命令还是走 MCP | 仅提示 | 「Use CLI tools」 |

**其他产品怎么套用**：每张检查项卡片带一个 `applies_to` 字段。Codex 的 B1 依据换成 Codex best practices，C2 换成 AGENTS.md 文档；某产品不记录这个信号时，自动判为 `na`，并写明“该产品不记录 X”。

### 2.4 每项改进建议怎么写

固定四段，由脚本从检查项库里取出“处方模板”，模型只负责把用户的数字填进去、润色成人话：

```
【发现】你三周 35 个会话，最长一个 56 条消息，一次 /clear 都没用过。
【为什么要改】官方原话（≤15 字引用 + 链接）：上下文越满，Claude 越容易忘掉前面的指令。
【怎么做】（三选一，带复制按钮）
   命令：  /clear          ← 换任务前打一下
   提示词：“把这次的结论写进 HANDOFF.md，然后我会 /clear 开新会话。”
   配置：  在 CLAUDE.md 加一行：# Compact instructions 保留修改过的文件清单和测试命令
【复测看什么】下次体检时 A1 的“最长会话消息数”应降到 30 以内。
```

规则：

- 每条处方必须属于三类之一：**命令 / 提示词 / 配置片段**。不写“建议多注意”这种空话。
- 处方模板在检查项库里人工审定，模型不能现编命令；模型只能改措辞，不能改命令本身。
- 涉及 Claude Code 官方已有的修复工具时，处方就是那个工具（`/doctor`、`/skill-doctor`、`/fewer-permission-prompts`、`/init`）。

### 2.5 视觉方向

**HTML 报告**

- 单文件，内联 CSS 和 SVG，不加载外部字体或 CDN（离线可开、不泄露访问记录）。
- 风格参考体检单：顶部大号总分环 + 四个分区的小环；卡片用四种状态色（绿 / 橙 / 灰蓝 / 浅灰），同时配图标和文字，色盲也能分辨。
- 自动适配浅色和深色模式；中文字体回退链 `-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`。
- 处方的代码块带“复制”按钮（几行内联 JS）。
- 复测时，每张卡片右上角显示 `↑ 12` / `↓ 3` 的变化徽标。

**分享卡**

- 两个尺寸：1200×675（X 横图）、1080×1350（小红书竖图）。
- 内容只包括：总分与等级、四区小分、3 个“亮点数字”（如“缓存命中 98%”“用过 5 个 Skill / 装了 121 个”“0 次子代理”）、一句模型写的“体检结论”（≤ 20 字）、所用 Agent 的名字、统计天数、项目名或二维码位（可关）。
- **默认不出现**：项目名、路径、用户名、会话标题、提示词原文、仓库地址。
- 生成方式：脚本输出 SVG（纯标准库就能写）和一个只放这张卡的 HTML；转 PNG 按顺序尝试：Agent 自带的浏览器截图 → macOS `qlmanage -t` → 提示用户手动截图。见待定问题 Q4。

---

## 3. 如何真正帮用户用得更好

### 3.1 看完报告之后做什么

报告第 ⑦ 区“改进清单”只列 **5 条**，按“省事程度 × 影响”排序，并分成三栏：

- **现在就改（1 分钟）**：一条命令，比如 `/init`、`/doctor`、在设置里关掉不用的 MCP。
- **下次会话就用（养习惯）**：一段可以存进剪贴板的提示词，比如“先用子代理调研 X，只回报结论”。
- **花 10 分钟配好（一劳永逸）**：一段配置，比如 CLAUDE.md 模板、hooks 片段、`skillOverrides`。

另外报告最后附一段“让 Agent 帮我改”的总提示词：把 5 条处方拼成一个任务，交给用户自己的 Agent 执行，并要求它**每改一处配置都先展示 diff、再等确认**。

### 3.2 复测

需要做，这是和 `/insights` 最大的差别之一。

- 每次运行都把 `facts.json`（只有数字，没有原文）存到 `~/.agent-usage-report/history/<日期>.json`。
- 复测时自动找最近一份历史记录做对比，报告第 ⑥ 区给出：总分变化、哪几项从 bad 变成 good、哪几项退步。
- 复测窗口的默认值：从上次体检的时间点到现在，而不是固定 30 天。这样“改完之后”的行为不会被“改之前”的数据稀释。也支持 `--since`。
- 复测最早的提醒时机：距离上次体检至少 7 天，且新增了 ≥ 10 个会话。不够时报告提示“样本还太少，再用几天”。
- 分享卡支持“前后对比”版式：`62 → 81`。

---

## 4. 技术方案

### 4.1 总体流程

```
[1 探测]  scan.py detect           → 检测到哪些 Agent、版本、数据量、预计耗时
[2 统计]  scan.py collect --days 30 → facts.json（纯数字 + 脱敏样例），约几秒到一分钟
[3 判定]  scan.py score            → findings.json（每项检查的 good/bad/unused/na + 处方模板 ID）
[4 解读]  模型读 facts.json + findings.json（通常 < 30 KB），写总评、每项的“发现”句、三条本周就改
[5 渲染]  scan.py render           → report.html + share-card.svg/.html（模板由脚本填，模型的文字作为 JSON 传入）
```

**模型从头到尾不读原始记录。** 模型能看到的只有 `facts.json` 和 `findings.json`；需要举例时，只能用脚本挑出、已经脱敏的短片段（见 4.4）。这样既不会读不完、不会烧额度，所有数字也都能对回脚本的输出，模型没有编数字的机会。为防止编造，渲染器会校验模型返回的文字：其中出现的数字必须能在 facts 里找到，否则标黄提示。

### 4.2 脚本语言：Python 3，仅用标准库

| 方案 | 优点 | 缺点 |
|---|---|---|
| **Python 3.9+ 标准库（推荐）** | `json`、`sqlite3`、`glob` 都内置；macOS 装了开发者工具就有 `python3`，Linux 普遍自带；单文件就能分发；Agent 写和改都最熟 | Windows 默认没有 Python；`zstd` 要到 3.14 才进标准库 |
| Node.js | Claude Code / Codex 的 npm 用户一定有 | 桌面 App 用户未必有；`sqlite` 要到 Node 22.5+ 才内置 |
| 编译型单文件（Go / Rust） | 零依赖、最快 | 小白不敢跑来历不明的二进制；Agent 也不方便现场修改；发布要多平台构建 |

降级策略：

- 没有 `python3` 时，Skill 让 Agent 依次尝试 `uv run --python 3.12`，然后给出安装指引。Windows 用户提示 `winget install Python.Python.3.12`。
- 读 `.zst` 的三级降级：`compression.zstd`（3.14+）→ 系统 `zstd -dc` 子进程 → 跳过这些文件，改用 `state_5.sqlite` 的会话级元数据，并在报告里写明“Codex 7 天前的会话只有会话级数据”。
- SQLite 一律用 `file:...?mode=ro` 只读打开，不 checkpoint WAL，不写入。

### 4.3 统一事件模型（适配器的输出）

```text
Session  { agent, entrypoint, session_id, project_key(哈希), started_at, ended_at,
           is_subagent, parent_id, version, model_set, permission_modes }
Event    { session_id, ts, kind, ... }
  kind = user_message      { chars, is_slash, slash_name, has_file_ref, is_short, neg_start }
       | tool_call         { tool, category(read/edit/bash/web/browser/mcp/skill/agent/plan/ask), mcp_server, skill_name }
       | bash_command      { family(test/build/lint/git/other) }   ← 只存分类，不存命令原文
       | interrupt         { by_user }
       | compaction        { auto }
       | mode_change       { mode }
       | usage             { model, input, output, cache_read, cache_write }
       | error             { category(rate_limit/context/api/tool) }
```

- `project_key` 用路径的加盐哈希，报告里显示成“项目 A / 项目 B”；只有用户在本机打开完整报告、并且加上 `--show-projects` 时，才显示真名。
- 每个适配器自带一个**版本探针**：读文件头几行，判断字段集合，选对应的解析分支；识别不了的行计入 `unknown_lines`。报告页头显示“数据完整度 97%（2,113 行无法识别）”。
- 各产品的原始字段怎么映射到统一模型，写在适配器顶部的注释表里（例如 Claude Code `system.subtype=compact_boundary` 对应 compaction；Codex 的 `compacted` 和 `contextCompaction` 也对应 compaction）。

### 4.4 隐私

1. **只在本机运行**：脚本不导入任何网络库；CI 里加一条测试，静态扫描代码，禁止出现 `urllib`、`http`、`socket`。
2. **不读不存原文**：统计时只提取长度、计数、分类。提示词、代码、命令输出都不进 facts.json。
3. **脱敏样例**：报告需要举例时（如“你最常见的短消息”），只允许从白名单里取：长度 ≤ 12 字的用户消息，以及斜杠命令名。正则会替换掉路径、邮箱、URL、token 形状的串、长数字，替换后才给模型看。
4. **分享卡默认零标识**：不出项目名、路径、用户名、主机名、会话标题。渲染器最后再做一道检查，卡片文本里命中路径分隔符或 `@` 就拒绝输出。
5. **输出位置**：`~/.agent-usage-report/`（报告、历史 facts），不写进任何项目目录，避免被误提交。
6. **模型那一步**：用的是用户自己的 Agent 和账号，送进去的只有 facts / findings，这一点和日常使用没有区别；报告附录里如实写明。

### 4.5 两种交付形式

| | A. 一段提示词（复制粘贴） | B. 开源 Skill（推荐主推） |
|---|---|---|
| 用户动作 | 复制一段 ~60 行的提示词，发给自己的 Agent | `npx skills add …` 或 git clone 到 skills 目录，然后说“给我做个体检” |
| 脚本来源 | 提示词要求 Agent **现场从 GitHub 下载固定版本的脚本**（带 sha256 校验），或者现场生成简版脚本 | Skill 自带 `scripts/`，版本固定 |
| 优点 | 零安装，适合放在文章结尾；任何 Agent 都能用 | 数字稳定可复现；能复测；检查项库和模板完整；可审计 |
| 缺点 | 现场生成脚本时，每次结果可能不同，数字可信度下降；下载脚本又要联网 | 要安装一次；需要按各产品的 Skill 目录分别装（或装到 `~/.agents/skills` 共享） |
| 定位 | “试吃装”：只出简版报告（A、C 两区 + 分享卡），结尾引导安装 Skill | “正式版”：全部四区 + 跨 Agent + 复测 |

**建议**：文章结尾两样都放。提示词版走“下载固定版本脚本 + 校验哈希”的路线，不让 Agent 现编统计逻辑，否则“数字会编”的问题又回来了。如果用户的环境不能联网，提示词给出降级方案：只做配置体检（ls 和 wc 就够了），并明确告诉用户“使用习惯部分需要装 Skill”。

### 4.6 Skill 目录结构

```
agent-usage-report/
├── SKILL.md                    # 触发词：体检、使用报告、我用得怎么样；流程 5 步；隐私声明
├── scripts/
│   ├── scan.py                 # CLI 入口：detect / collect / score / render / diff
│   ├── collectors/
│   │   ├── base.py
│   │   ├── claude_code.py
│   │   ├── codex.py
│   │   ├── cursor_config.py    # v1 只读配置
│   │   ├── opencode.py         # v1.1
│   │   ├── pi.py               # v1.1
│   │   └── gemini_cli.py       # v1.1
│   ├── metrics.py
│   ├── redact.py
│   └── render.py
├── checks/
│   ├── common.yaml             # 检查项：id、指标、阈值、判定、依据 URL、处方模板（命令/提示词/配置）
│   ├── claude_code.yaml
│   └── codex.yaml
├── templates/
│   ├── report.html
│   └── share-card.svg
├── references/
│   ├── data-locations.md       # 第 1 节的表，供 Agent 在格式变化时自查
│   └── metrics.md              # 统计口径
├── prompt/
│   └── quick-prompt.md         # 交付形式 A 的那段提示词
└── tests/
    └── fixtures/               # 每个产品、每个版本的脱敏样例
```

> `checks/*.yaml` 用 YAML 便于人工审阅，但标准库不带 YAML 解析器。实现时改成 JSON，或者用一个极简子集解析器；倾向 JSON，见 Q6。

### 4.7 版本变化时怎么降级

1. **探测优先**：适配器先看字段和表名，不看版本号。认识就解析，不认识就跳过这一行并计数。
2. **分级可用**：完整（逐事件）→ 会话级（只有会话元数据）→ 仅配置 → 不可用。报告给每个 Agent 标出当前所处的级别。
3. **不阻塞**：任何一个适配器抛异常，都只影响它自己那一列，其他照常出报告。
4. **自愈提示**：未识别行超过 20% 时，报告提示“X 的记录格式可能更新了”，并附一段给 Agent 的提示词：“读 `references/data-locations.md` 和 3 行样本的**字段名**（不读值），帮我更新 collectors/x.py”。修复的 PR 欢迎回馈到仓库。
5. **夹具回归**：每发现一个新版本，就往 `tests/fixtures/` 加一份脱敏样本；CI 跑所有版本。

### 4.8 性能

本机 Claude Code 1.2 GB、Codex 4.2 GB，所以采用流式逐行读取：先按文件修改时间过滤掉窗口外的文件；对 JSONL 先做字符串预筛（例如先判断 `'"type":"assistant"' in line`），再决定要不要 `json.loads`。目标是 30 天窗口、5 GB 数据在 60 秒内跑完；超过时显示进度。

---

## 5. 关键决策与待用户拍板的问题

**已经定的（如无异议照此执行）**

- 第一版正式支持 **Claude Code + Codex**，Cursor 只做配置体检；OpenCode、pi、Gemini CLI 放在 v1.1，通过适配器契约扩展。
- 定位“体检单 + 复查单”：逐项打分、数字可复核、跨 Agent、可复测、能晒。不做叙事式复盘（那是 `/insights` 的事），配置自动修复交给 `/doctor`。
- Python 3.9+，只用标准库；模型只读汇总后的 facts / findings，不读原始记录；渲染器校验模型写的数字。
- 默认窗口 30 天，与 Claude Code 默认保留期一致；复测窗口默认从上次体检的时间点开始。
- 输出放 `~/.agent-usage-report/`，分享卡默认零标识。

**待拍板**

| # | 问题 | 选项 | 我的建议 |
|---|---|---|---|
| Q1 | 第一版是否要带上 Cursor 的会话分析 | 只查配置 / 读 `state.vscdb` 实验版 | 只查配置，避免内部格式一变就出错数 |
| Q2 | 是否读取 `/insights` 的缓存（`~/.claude/usage-data/`）来补充“摩擦”类信息 | 读（有就用）/ 不读 | 不读，保持“数字全部来自原始记录”的口径；作为 v2 可选项 |
| Q3 | 提示词版本里的脚本怎么来 | 从 GitHub 下载固定版本 + 哈希校验 / 让 Agent 现场生成简版 | 下载固定版本；现场生成会让数字不可复现 |
| Q4 | 分享卡输出 PNG 的方式 | 只出 SVG / HTML 让用户截图；或者依赖 Agent 浏览器截图 | 先出 SVG + HTML，有浏览器工具就自动截 PNG |
| Q5 | 总分要不要 | 出总分（好传播）/ 只出分区等级（更稳） | 出总分，但样本不够时隐藏，并在卡片注明“满分不代表会用” |
| Q6 | 检查项库格式 | YAML（易读，需要自写解析）/ JSON（标准库直接读） | JSON |
| Q7 | 开源仓库名与许可证 | `agent-usage-report` / 其他；MIT / Apache-2.0 | `agent-usage-report` + MIT |
| Q8 | 经验阈值（A4、B2、B3、C3、D2）要不要先在作者本机和 2–3 位朋友的数据上校准再定 | 校准 / 先用拍定值 | 校准；用三周体检报告当第一份基线 |

---

## 6. 调研出处

**本机实测**（2026-10-26，只读，未修改任何文件）

- `~/.claude/projects/*/*.jsonl`：记录类型统计（assistant / user / attachment / system / mode / cost-state 等），以及字段 `entrypoint`、`permissionMode`、`version`；`*/subagents/*.jsonl` 共 123 个
- `~/.claude.json`：`skillUsage`（19 个 Skill 有调用记录）、`pluginUsage`、`projects.*.allowedTools`；`~/.claude/settings.json`；`~/.claude/skills`（69 个）
- `~/.claude/usage-data/`：`/insights` 报告的章节结构，以及 `session-meta`、`facets` 的字段
- `~/.codex/sessions`（51 个 `.jsonl` + 918 个 `.jsonl.zst`）、`state_5.sqlite`（`threads` 表）、`thread_history_1.sqlite`（`thread_items` 表，item_type 分布）、`config.toml` 各段
- `~/.cursor/projects/*/agent-transcripts/*.jsonl`（字段只有 role / message / type / status / error）、`globalStorage/state.vscdb`、`~/.cursor/mcp.json`、`cli-config.json`、`rules/*.mdc`
- `~/.local/share/opencode/opencode.db`（`session_v2`、`session_message` 的表结构，迁移 50 条）、`~/.config/opencode/opencode.json`
- `~/.gemini/`（只有 Antigravity 的 protobuf，没有 Gemini CLI 会话）、`~/.pi/agent/skills`、`~/.agents/skills`

**官方文档**

- Claude Code 命令（`/insights`、`/doctor`、`/usage`、`/fewer-permission-prompts`、`/init`）：https://code.claude.com/docs/en/commands
- Claude Code 最佳实践：https://code.claude.com/docs/en/best-practices
- `/insights` 的范围、位置与成本，以及“CLAUDE.md 控制在 200 行内”：https://code.claude.com/docs/en/costs
- `/doctor` 与 `/skill-doctor`、Skill 位置、Skill 的上下文代价：https://code.claude.com/docs/en/skills
- `~/.claude` 目录、Windows 路径、30 天清理、明文存储：https://code.claude.com/docs/en/claude-directory
- Codex 配置参考：https://learn.chatgpt.com/docs/config-file/config-reference（原 developers.openai.com/codex/config-reference）
- Codex 最佳实践：https://developers.openai.com/codex/learn/best-practices
- Codex AGENTS.md：https://developers.openai.com/codex/guides/agents-md
- Codex Skills：https://developers.openai.com/codex/skills
- Cursor 规则：https://cursor.com/docs/context/rules
- Cursor Agent 概览：https://cursor.com/docs/agent/overview
- Cursor Agent 最佳实践：https://cursor.com/blog/agent-best-practices
- Gemini CLI 会话管理：https://geminicli.com/docs/cli/session-management/
- Gemini CLI checkpointing：https://google-gemini.github.io/gemini-cli/docs/cli/checkpointing.html
- pi 会话格式：https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/session-format.md

**社区资料（只作为交叉验证，不作为打分依据）**

- Codex 记录 7 天后压缩为 zst、`state_5.sqlite` 的用途：https://vshulcz.github.io/deja-vu/guide/codex-history.html
- Cursor `state.vscdb` 结构与 transcripts 不完整：https://vibe-replay.com/blog/cursor-local-storage/ 、https://github.com/kenn-io/agentsview/issues/1515
- OpenCode 迁移到 SQLite 与 v2 schema：https://github.com/anomalyco/opencode/issues/13654 、https://github.com/panrafal/paseo-plugins/issues/14

---

## 7. 实现备注（v0.1.0，2026-10-26）

按第 5 节的建议定稿（Q1–Q8 全部采用推荐项）后实现。和上文设计不一致的地方：

- **分享卡 PNG**：本来打算用 macOS `qlmanage` 转 PNG，实测它只出正方形缩略图，会把竖版卡片裁掉。改成在 `share-card.html` 里内联 SVG，加一个“下载 PNG”按钮（canvas 2 倍导出），任何浏览器都能用，Agent 有浏览器工具时也能点。
- **B2 验证 / B1 Plan / B7 审查**：只看“改过代码的会话”。只改 Markdown 这类文档的会话不要求跑测试。
- **D4 并行**：不按会话首尾时间算重叠，改成 30 分钟时间片。桌面 App 的会话会开好几天，按首尾时间算会虚高。
- **D1 模型分档**：阈值从 90% 降到 75%，以三周体检报告的人工判断为基线校准，详见 `references/metrics.md`。
- **D3、D5**：D3（意外中断）只在 `facts.json` 里记录，不出卡片；D5（CLI 代替 MCP）第一版没做。
- **统一事件模型**：采集器直接产出“会话统计”（`SessionStats`），不逐条产出事件，省内存也更快；字段含义与 4.3 节一致。
- **报告改版（第二轮）**：新增置顶导航、体检单矩阵（检查项 × Agent）、使用画像（每天 / 每小时消息分布，带悬停数值和数据表）、功能雷达、卡片证据列表、可勾选的改进清单、深浅色切换；配色改用 dataviz 默认色板，Agent 身份色为第 1、2 槽，状态色用保留的 good / warning / serious 并配图标和文字。口径调整见 `references/metrics.md` 的“第二轮”校准记录。
