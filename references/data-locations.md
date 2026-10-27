# 各产品的数据位置与格式

> 给维护者和 Agent 看：记录格式变了、需要更新采集器时先读这里。只看**字段名**，不要把字段值（提示词、代码）读进上下文。
> 调研日期 2026-10-26，出处见 docs/design.md 第 6 节。

## Claude Code（终端、桌面 App Code 标签、VS Code 插件）

| 内容 | 位置 |
|---|---|
| 会话记录 | `~/.claude/projects/<路径里非字母数字换成 ->/<session>.jsonl`（`CLAUDE_CONFIG_DIR` 可改根目录；Windows 是 `%USERPROFILE%\.claude`） |
| 子代理记录 | `~/.claude/projects/<项目>/<session>/subagents/agent-*.jsonl` |
| 保留期 | `cleanupPeriodDays`，默认 30 天；桌面 App 的会话默认不按年龄清理 |
| 全局规则 | `~/.claude/CLAUDE.md`、`~/.claude/rules/*.md` |
| 项目规则 | `CLAUDE.md`、`CLAUDE.local.md`、`.claude/CLAUDE.md`、`.claude/rules/*.md`；没有 CLAUDE.md 时读 `AGENTS.md`；父目录也会加载 |
| Skill | `~/.claude/skills/*/SKILL.md`、`.claude/skills/`、插件的 `skills/` |
| 插件 | `~/.claude/plugins/installed_plugins.json`（`plugins.<名>[].installPath`），启用状态看 `settings.json` 的 `enabledPlugins` |
| MCP | `~/.claude.json` 的 `mcpServers` 和 `projects.<路径>.mcpServers`；项目 `.mcp.json`；插件目录的 `.mcp.json` |
| 权限 / hooks | `~/.claude/settings.json`、`.claude/settings.json`、`.claude/settings.local.json` 的 `permissions`、`hooks` |

关键字段（jsonl 每行一条）：

- `type`: `user` / `assistant` / `system` / `attachment` / `mode` / `cost-state` / `api-request*`（跳过）/ `file-history-*`（跳过）
- `entrypoint`: `cli`、`claude-desktop`、`claude-desktop-3p`、`claude-vscode`、`sdk-*`
- `user.permissionMode`: `default` / `acceptEdits` / `plan` / `auto` / `bypassPermissions`
- `user.origin.kind`: `human` 才是人发的；`task-notification` 等不算
- 斜杠命令：用户文本里的 `<command-name>/xxx</command-name>`
- 打断：用户文本 `[Request interrupted by user`
- `assistant.message.content[].type=tool_use` 的 `name` / `input`；`message.usage` 按 `message.id` 去重
- `system.subtype=compact_boundary`，`compactMetadata.trigger` = `auto` / `manual`
- `attachment.type`: `queued_command`（工作中追加的消息，`commandMode=prompt`）、`plan_mode`、`goal_status`、`skill_mention`

## Codex（CLI、App、IDE 插件）

| 内容 | 位置 |
|---|---|
| 会话记录 | `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<时间>-<id>.jsonl`；**7 天后压缩为 `.jsonl.zst`**；`archived_sessions/` 同格式 |
| 会话列表 | `state_5.sqlite` 的 `threads` 表（模型、审批模式、沙箱、token 总数、来源） |
| 逐条记录副本 | `thread_history_1.sqlite` 的 `thread_items` 表 |
| 全局规则 | `~/.codex/AGENTS.md`、`AGENTS.override.md` |
| 项目规则 | 从仓库根到当前目录逐级的 `AGENTS.md` / `AGENTS.override.md`，总长受 `project_doc_max_bytes` 限制 |
| Skill | `~/.agents/skills`、`.agents/skills`（官方）；`~/.codex/skills`（旧位置） |
| 配置 | `~/.codex/config.toml`：`approval_policy`、`sandbox_mode`、`model_reasoning_effort`、`[mcp_servers.*]`、`[plugins.*]`、`[hooks]`；另有 `hooks.json`、`rules/*.rules` |

关键字段（每行 `{"timestamp","type","payload"}`）：

- `session_meta.payload`: `id`、`cwd`、`originator`（`Codex Desktop` 等）、`cli_version`、`source`（字符串，或 `{"subagent": ...}`）
- `turn_context.payload`: `model`、`approval_policy`、`sandbox_policy.type`、`collaboration_mode.mode`（`plan` / `default`）、`collaboration_mode.settings.reasoning_effort`
- 新版：`event_msg.payload.type=item_completed`，`item.type` = `UserMessage` / `CommandExecution` / `FileChange` / `McpToolCall` / `WebSearch` / `SubAgentActivity` / `ContextCompaction` / `Reasoning` / `AgentMessage`（大小写可能变，按忽略大小写和下划线比较）
- 旧版：`response_item` 的 `message(role=user)`、`function_call(name=shell|exec_command)`、`custom_tool_call(name=apply_patch)`；`event_msg.user_message`
- `event_msg.token_count.info.total_token_usage`：累计值，取最大的一条
- `event_msg.turn_aborted.reason=interrupted`、`event_msg.thread_goal_updated`
- 顶层 `compacted`：一次压缩

## Cursor（第一版只读配置）

| 内容 | 位置 |
|---|---|
| 会话主库 | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`（Windows `%APPDATA%\Cursor\User\...`，Linux `~/.config/Cursor/User/...`），`cursorDiskKV` 表的 `composerData:*`、`bubbleId:*`，内部格式 |
| 导出副本 | `~/.cursor/projects/<路径>/agent-transcripts/<id>/<id>.jsonl`，只有 role / message，无时间戳和模型 |
| 规则 | `.cursor/rules/*.mdc`、`~/.cursor/rules`、`AGENTS.md` |
| Skill / MCP / 权限 | `~/.cursor/skills`、`~/.cursor/mcp.json`、`~/.cursor/cli-config.json` 的 `permissions` |

## v1.1 计划中的产品

- **OpenCode**：`~/.local/share/opencode/opencode.db`。新版表 `session_v2`（自带 token、cost 汇总）、`session_message(type, data)`；旧版 `storage/session|message|part/*.json`。先探测表名再选解析器。
- **pi**：`~/.pi/agent/sessions/--<路径>--/<时间>_<id>.jsonl`，首行 `{"type":"session","version":3,...}`，消息按 `id/parentId` 成树。格式文档：badlogic/pi-mono `packages/coding-agent/docs/session-format.md`。
- **Gemini CLI**：`~/.gemini/tmp/<project_hash>/chats/`，JSON，默认保留 30 天（`general.sessionRetention`）。
