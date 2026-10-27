"""在临时目录里造一个“家目录”，里面是结构仿真、内容虚构的 Claude Code 和 Codex 记录。

字段结构来自真实记录（见 references/data-locations.md），文字全部是编的。
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime.now(timezone.utc)


def ts(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def jl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def user(text, t, cwd, sid, **extra):
    d = {"type": "user", "message": {"role": "user", "content": text}, "timestamp": ts(t), "cwd": cwd,
         "sessionId": sid, "entrypoint": "cli", "version": "2.1.300", "permissionMode": "auto",
         "origin": {"kind": "human"}}
    d.update(extra)
    return d


def tool_result(t, cwd, sid):
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]},
            "timestamp": ts(t), "cwd": cwd, "sessionId": sid}


def assistant(mid, t, cwd, sid, tools=(), model="claude-opus-5-5", usage=None):
    content = [{"type": "tool_use", "id": "tu" + str(i), "name": n, "input": inp} for i, (n, inp) in enumerate(tools)]
    return {"type": "assistant", "timestamp": ts(t), "cwd": cwd, "sessionId": sid, "entrypoint": "cli",
            "message": {"id": mid, "model": model, "role": "assistant", "content": content,
                        "usage": usage or {"input_tokens": 10, "output_tokens": 20,
                                           "cache_read_input_tokens": 900, "cache_creation_input_tokens": 50}}}


def build_home(root: Path, with_zst: bool = True) -> dict:
    """返回 {home, proj_a, proj_b, secret_project_name}。"""
    home = root / "home"
    proj_a = root / "work" / "secret-alpha-app"
    proj_b = root / "work" / "beta-notes"
    for p in (proj_a, proj_b):
        p.mkdir(parents=True)
    # 项目 A 有 CLAUDE.md（含一个假密钥）和 AGENTS.md
    (proj_a / "CLAUDE.md").write_text("# Rules\n- run npm test\n- api_key = abcdefghijklmnop1234\n", encoding="utf-8")
    (proj_a / "AGENTS.md").write_text("# Agents\n" + "- rule\n" * 10, encoding="utf-8")

    # ---------- Claude Code ----------
    cl = home / ".claude"
    (cl / "skills" / "01-writer-dir").mkdir(parents=True)
    (cl / "skills" / "01-writer-dir" / "SKILL.md").write_text("---\nname: writer\ndescription: x\n---\n", encoding="utf-8")
    for i in range(3):
        d = cl / "skills" / "unused-{}".format(i)
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: unused-{}\n---\n".format(i), encoding="utf-8")
    (cl / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(npm test)"]},
                                                  "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "x"}]}]}}))
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"notion": {}, "github": {}},
                                                   "skillUsage": {"writer": {"usageCount": 3}}}))
    a = str(proj_a)
    enc = "-" + a.strip("/").replace("/", "-")
    s1 = "11111111-aaaa"
    rows = [
        user("帮我在 src/app.ts 里加一个登录按钮，完成后跑测试", 600, a, s1),
        assistant("m1", 599, a, s1, tools=[("Read", {"file_path": a + "/src/app.ts"}),
                                           ("Edit", {"file_path": a + "/src/app.ts"})]),
        assistant("m1", 599, a, s1),  # 同一个 message.id 的第二个分块，usage 不能重复算
        tool_result(598, a, s1),
        assistant("m2", 597, a, s1, tools=[("Bash", {"command": "npm test"})]),
        user("继续", 590, a, s1),
        user("<command-name>/clear</command-name>\n<command-message>clear</command-message>", 585, a, s1),
        user("<command-name>/model</command-name>\n<command-args>sonnet</command-args>", 584, a, s1),
        user("[Request interrupted by user]", 583, a, s1),
        user("<task-notification>done</task-notification>", 582, a, s1, origin={"kind": "task-notification"}),
        user("meta stuff", 581, a, s1, isMeta=True),
        {"type": "system", "subtype": "compact_boundary", "compactMetadata": {"trigger": "auto"}, "timestamp": ts(580), "sessionId": s1},
        {"type": "attachment", "attachment": {"type": "queued_command", "prompt": "顺便把 README 也改一下", "commandMode": "prompt"},
         "timestamp": ts(579), "sessionId": s1},
        {"type": "attachment", "attachment": {"type": "plan_mode"}, "timestamp": ts(578), "sessionId": s1},
        assistant("m3", 577, a, s1, tools=[("Skill", {"skill": "01-writer-dir"}), ("Agent", {"subagent_type": "Explore", "description": "调研"}),
                                           ("mcp__notion__search", {}), ("AskUserQuestion", {})], model="claude-sonnet-5-5"),
        {"type": "system", "subtype": "api_error", "error": {"status": 429}, "timestamp": ts(576), "sessionId": s1},
        {"type": "api-request-blob", "hash": "h", "message": {}, "sessionId": s1},
        "this line is not json",
    ]
    f1 = cl / "projects" / enc / (s1 + ".jsonl")
    f1.parent.mkdir(parents=True)
    with open(f1, "w", encoding="utf-8") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n")
    jl(cl / "projects" / enc / s1 / "subagents" / "agent-abc.jsonl", [
        user("调研任务说明", 577, a, s1, isSidechain=True),
        assistant("sm1", 576, a, s1, tools=[("Read", {"file_path": "x"})]),
    ])
    # 同一个项目的另一个短会话：让项目 A 成为“常用项目”（≥2 个会话）
    jl(cl / "projects" / enc / "33333333-cccc.jsonl", [user("看一下 README", 200, a, "33333333-cccc")])
    # 第二个 Claude 会话：只改 markdown，在窗口外有一条旧消息
    s2 = "22222222-bbbb"
    b = str(proj_b)
    encb = "-" + b.strip("/").replace("/", "-")
    # 桌面 App 从账号同步的插件 Skill：只有用过桌面版时才算
    dp = home / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions" / "acct" / "org" / "rpm" / "plugin_x" / "skills" / "standup"
    dp.mkdir(parents=True)
    (dp / "SKILL.md").write_text("---\nname: standup\n---\n")
    jl(cl / "projects" / encb / (s2 + ".jsonl"), [
        user("很久以前的消息", 60 * 24 * 60, b, s2, entrypoint="claude-desktop"),
        user("把这篇文章改得口语一点", 300, b, s2, permissionMode="bypassPermissions"),
        assistant("n1", 299, b, s2, tools=[("Write", {"file_path": b + "/draft.md"})]),
        user("不对", 298, b, s2, permissionMode="bypassPermissions"),
        user("还是不行", 297, b, s2, permissionMode="bypassPermissions"),
        user("不对，重来", 296, b, s2, permissionMode="bypassPermissions"),
    ])

    # ---------- Codex ----------
    cx = home / ".codex"
    cx.mkdir(parents=True)
    (cx / "AGENTS.md").write_text("global rule\n", encoding="utf-8")
    (cx / "config.toml").write_text(
        'model = "gpt-6.1-sol"\napproval_policy = "never"\nsandbox_mode = "danger-full-access"\n'
        '[mcp_servers.node_repl]\ncommand = "node"\n[plugins."github@openai-curated"]\nenabled = true\n', encoding="utf-8")
    (home / ".agents" / "skills" / "playwright").mkdir(parents=True)
    (home / ".agents" / "skills" / "playwright" / "SKILL.md").write_text("---\nname: playwright\n---\n")
    (home / ".agents" / "skills" / "writer").mkdir(parents=True)
    (home / ".agents" / "skills" / "writer" / "SKILL.md").write_text("---\nname: writer\n---\n")
    day = NOW.strftime("%Y/%m/%d")
    sess = cx / "sessions" / day
    tc = {"model": "gpt-6.1-sol", "approval_policy": "never", "sandbox_policy": {"type": "danger-full-access"},
          "collaboration_mode": {"mode": "plan", "settings": {"reasoning_effort": "high"}}, "cwd": a}

    def ev(t, typ, payload):
        return {"timestamp": ts(t), "type": typ, "payload": payload}

    def item(t, it):
        return ev(t, "event_msg", {"type": "item_completed", "item": it})

    new_rows = [
        ev(500, "session_meta", {"id": "cx-new", "cwd": a, "originator": "Codex Desktop", "cli_version": "0.164.0", "source": "vscode"}),
        ev(499, "turn_context", tc),
        ev(499, "response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions"}]}),
        item(499, {"type": "UserMessage", "content": [{"type": "text", "text": "用 $playwright 检查一下页面 src/page.tsx"}]}),
        item(498, {"type": "FileChange", "changes": {a + "/src/page.tsx": {"type": "update"}, a + "/notes.md": {"type": "add"}}}),
        item(497, {"type": "CommandExecution", "command": ["bash", "-lc", "pnpm run build"], "parsed_cmd": []}),
        item(496, {"type": "CommandExecution", "command": ["bash", "-lc", "cat ~/.agents/skills/playwright/SKILL.md"],
                   "parsed_cmd": [{"type": "read", "path": str(home) + "/.agents/skills/playwright/SKILL.md"}]}),
        item(495, {"type": "McpToolCall", "server": "node_repl", "tool": "run"}),
        item(494, {"type": "SubAgentActivity", "kind": "started", "agent_path": "/root/static_review"}),
        item(493, {"type": "ContextCompaction", "id": "c1"}),
        ev(493, "compacted", {"message": ""}),
        ev(492, "event_msg", {"type": "turn_aborted", "reason": "interrupted"}),
        ev(491, "event_msg", {"type": "thread_goal_updated", "goal": {}}),
        ev(490, "event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 1000, "cached_input_tokens": 900, "output_tokens": 50, "total_tokens": 1050}}}),
        ev(489, "event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 500, "cached_input_tokens": 400, "output_tokens": 10, "total_tokens": 510}}}),
    ]
    jl(sess / "rollout-{}-cx-new.jsonl".format(NOW.strftime("%Y-%m-%dT%H-%M-%S")), new_rows)
    # 旧格式：没有 item_completed，只有 response_item
    old_rows = [
        ev(400, "session_meta", {"id": "cx-old", "cwd": b, "originator": "codex_cli_rs", "cli_version": "0.40.0", "source": "cli"}),
        ev(399, "turn_context", {"model": "gpt-5", "approval_policy": "on-request", "sandbox_policy": {"type": "workspace-write"}, "cwd": b, "effort": "medium"}),
        ev(399, "response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>x</environment_context>"}]}),
        ev(398, "response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "修一下 bug"}]}),
        ev(397, "response_item", {"type": "function_call", "name": "shell", "arguments": json.dumps({"command": ["bash", "-lc", "pytest -q"]})}),
        ev(396, "response_item", {"type": "custom_tool_call", "name": "apply_patch", "input": "*** Begin Patch\n*** Update File: app.py\n*** End Patch"}),
    ]
    old_path = sess / "rollout-{}-cx-old.jsonl".format(NOW.strftime("%Y-%m-%dT%H-%M-%S"))
    jl(old_path, old_rows)
    zst_written = False
    if with_zst:
        zst_written = _to_zst(old_path)
    # 程序调起的会话（canvas-agent），不计入使用习惯
    jl(sess / "rollout-{}-cx-auto.jsonl".format(NOW.strftime("%Y-%m-%dT%H-%M-%S")), [
        ev(450, "session_meta", {"id": "cx-auto", "cwd": a, "originator": "canvas-agent", "source": "vscode"}),
        item(449, {"type": "UserMessage", "content": [{"type": "text", "text": "自动任务"}]}),
    ])
    # 子代理会话
    jl(sess / "rollout-{}-cx-sub.jsonl".format(NOW.strftime("%Y-%m-%dT%H-%M-%S")), [
        ev(494, "session_meta", {"id": "cx-sub", "cwd": a, "source": {"subagent": {"thread_spawn": {}}}}),
        item(493, {"type": "UserMessage", "content": [{"type": "text", "text": "审查任务"}]}),
    ])

    # ---------- Cursor（只配置） ----------
    (home / ".cursor" / "rules").mkdir(parents=True)
    (home / ".cursor" / "rules" / "a.mdc").write_text("x\n" * 600)
    (home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"magic": {}}}))
    return {"home": home, "proj_a": proj_a, "proj_b": proj_b, "secret": "secret-alpha-app", "zst": zst_written}


def _to_zst(path: Path) -> bool:
    data = path.read_bytes()
    try:
        from compression import zstd  # type: ignore

        Path(str(path) + ".zst").write_bytes(zstd.compress(data))
        path.unlink()
        return True
    except ImportError:
        pass
    try:
        r = subprocess.run(["zstd", "-q", "--rm", str(path), "-o", str(path) + ".zst"], capture_output=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
