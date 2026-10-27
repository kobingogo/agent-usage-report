"""Claude Code 采集器（终端、桌面 App Code 标签、VS Code 插件共用 ~/.claude/projects）。

原始字段 → 统一统计 的映射：
  user（非 isMeta、非工具结果、非压缩摘要、origin.kind=human 或无 origin）  → 用户消息
  user 文本里的 <command-name>/x</command-name>                            → 斜杠命令 x
  user 文本 "[Request interrupted by user"                                  → 用户打断
  user.permissionMode                                                       → 权限模式（按用户消息计）
  attachment.type=queued_command 且 commandMode=prompt                      → 用户消息（工作中追加）
  attachment.type=plan_mode / goal_status / skill_mention                   → 用过 Plan / goal / Skill
  assistant.message.content[].tool_use                                      → 工具调用（按 message.id 去重 usage）
  system.subtype=compact_boundary（compactMetadata.trigger=auto|manual）    → 压缩
  system.subtype=api_error                                                  → 错误
  <session>/subagents/agent-*.jsonl                                         → 子代理会话
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .base import (
    Collector,
    Detection,
    SessionStats,
    ancestors_until_home,
    dir_size,
    list_skills,
    load_json,
    parse_ts,
    read_jsonl,
    is_code_path,
    rule_file_info,
)

_SKIP_TYPES = ('"type":"api-request', '"type":"file-history', '"type":"atis-latch', '"type":"agent-name',
               '"type":"custom-title', '"type":"last-prompt', '"type":"queue-operation"')
_CMD = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
_SYNTHETIC_PREFIX = ("<task-notification", "<local-command", "Caveat:", "This session is being continued",
                     "<system-reminder", "<bash-input", "<bash-stdout", "<bash-stderr", "<user-memory-input",
                     "The app was quit while you were working")

READ_TOOLS = {"Read", "Glob", "Grep", "LS", "NotebookRead"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
BASH_TOOLS = {"Bash", "PowerShell", "BashOutput"}
WEB_TOOLS = {"WebSearch", "WebFetch"}
REVIEW_NAMES = {"code-review", "review", "security-review", "ultrareview"}


def tool_category(name: str) -> str:
    low = name.lower()
    if name in READ_TOOLS:
        return "read"
    if name in EDIT_TOOLS:
        return "edit"
    if name in BASH_TOOLS:
        return "bash"
    if name in WEB_TOOLS:
        return "web"
    if name in ("Agent", "Task"):
        return "agent"
    if name == "Skill":
        return "skill"
    if name in ("ExitPlanMode", "EnterPlanMode"):
        return "plan"
    if name == "AskUserQuestion":
        return "ask"
    if any(k in low for k in ("browser", "chrome", "playwright", "puppeteer", "preview_screenshot")) or low.endswith("__computer"):
        return "browser"
    if name.startswith("mcp__"):
        return "mcp"
    return "other"


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for x in content:
            if isinstance(x, dict) and x.get("type") == "text":
                parts.append(x.get("text") or "")
        return "\n".join(parts)
    return ""


def _has_tool_result(content) -> bool:
    return isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content)


class ClaudeCodeCollector(Collector):
    id = "claude_code"
    display_name = "Claude Code"

    def __init__(self, home: Path):
        super().__init__(home)
        base = os.environ.get("CLAUDE_CONFIG_DIR")
        self.root = Path(base) if base else home / ".claude"
        self.projects = self.root / "projects"
        self.global_json = home / ".claude.json"
        self.desktop_used = False  # collect() 之后才知道是否用过桌面版

    def desktop_plugin_roots(self) -> list:
        """桌面 App 从账号同步的插件（Cowork / Code 标签共用），只在桌面版的 Code 会话里加载。"""
        bases = [self.home / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"]
        appdata = os.environ.get("APPDATA")
        if appdata:
            bases.append(Path(appdata) / "Claude" / "local-agent-mode-sessions")
        roots = []
        for b in bases:
            if b.is_dir():
                roots += list(b.glob("*/*/rpm/plugin_*/skills")) + list(b.glob("skills-plugin/*/*/skills"))
        return roots

    # ---------- 探测 ----------
    def detect(self) -> Detection:
        found = self.projects.is_dir()
        det = Detection(self.id, self.display_name, found)
        if not found:
            if self.root.is_dir():
                det.level = "config"
                det.paths = [str(self.root)]
            return det
        det.paths = [str(self.projects)]
        det.size_bytes = dir_size([self.projects])
        det.level = "full"
        latest = None
        for f in self.projects.glob("*/*.jsonl"):
            if latest is None or f.stat().st_mtime > latest.stat().st_mtime:
                latest = f
        if latest:
            for line in read_jsonl(latest):
                if '"version"' in line:
                    try:
                        v = json.loads(line).get("version")
                    except ValueError:
                        continue
                    if v:
                        det.version = v
        return det

    # ---------- 会话 ----------
    def collect(self, since: datetime, until: datetime) -> list:
        out = []
        if not self.projects.is_dir():
            return out
        since_ts = since.timestamp()
        for proj in self.projects.iterdir():
            if not proj.is_dir():
                continue
            for f in proj.glob("*.jsonl"):
                if ".orphaned-" in f.name or f.stat().st_mtime < since_ts:
                    continue
                s = self._parse(f, since, until, is_sub=False)
                if s and s.user_msgs > 0:
                    out.append(s)
                    if s.entrypoint.startswith("claude-desktop"):
                        self.desktop_used = True
            for f in proj.glob("*/subagents/*.jsonl"):
                if f.stat().st_mtime < since_ts:
                    continue
                s = self._parse(f, since, until, is_sub=True)
                if s and s.total_lines > 0:
                    out.append(s)
        return out

    def _parse(self, path: Path, since: datetime, until: datetime, is_sub: bool):
        s = SessionStats(agent=self.id, session_id=path.stem, is_subagent=is_sub)
        seen_msg_ids = set()
        for line in read_jsonl(path):
            head = line[:240]
            if any(t in head for t in _SKIP_TYPES):
                continue
            # 带工具结果的 user 行很大且不是人发的消息，只在需要时解析
            if '"tool_result"' in line and '"type":"user"' in head and "interrupted by user" not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                s.unknown_lines += 1
                continue
            t = d.get("type")
            ts = parse_ts(d.get("timestamp"))
            if ts is not None and (ts < since or ts > until):
                continue
            if t not in ("user", "assistant", "system", "attachment", "mode", "cost-state"):
                if t is None:
                    s.unknown_lines += 1
                continue
            s.total_lines += 1
            s.touch(ts)
            if d.get("entrypoint") and s.entrypoint == "unknown":
                s.entrypoint = d["entrypoint"]
                s.automated = str(d["entrypoint"]).startswith("sdk")
            if d.get("version") and not s.version:
                s.version = d["version"]
            cwd = d.get("cwd")
            if cwd and not s.project_path:
                s.project_path = cwd
            if cwd and "/.claude/worktrees/" in cwd:
                s.worktree = True

            if t == "user":
                self._on_user(s, d)
            elif t == "assistant":
                self._on_assistant(s, d, seen_msg_ids)
            elif t == "system":
                st = d.get("subtype")
                if st == "compact_boundary":
                    meta = d.get("compactMetadata") or {}
                    if (meta.get("trigger") or "auto") == "manual":
                        s.compact_manual += 1
                    else:
                        s.compact_auto += 1
                elif st == "api_error":
                    err = d.get("error") or {}
                    status = err.get("status") if isinstance(err, dict) else None
                    if status == 429:
                        s.errors["rate_limit"] += 1
                    elif isinstance(status, int) and status >= 500:
                        s.errors["api"] += 1
                    else:
                        s.errors["other"] += 1
            elif t == "attachment":
                a = d.get("attachment") or {}
                at = a.get("type")
                if at == "queued_command" and a.get("commandMode") == "prompt":
                    txt = a.get("prompt") if isinstance(a.get("prompt"), str) else ""
                    if txt and not txt.lstrip().startswith("<"):
                        s.add_user_message(txt, ts)
                elif at == "plan_mode":
                    s.plan_used = True
                elif at == "goal_status":
                    s.goal_used = True
                elif at == "skill_mention" and a.get("skillName"):
                    s.skills[str(a["skillName"]).split(":")[-1]] += 1
        return s

    def _on_user(self, s: SessionStats, d: dict) -> None:
        if d.get("isMeta") or d.get("isCompactSummary") or (d.get("isSidechain") and not s.is_subagent):
            return
        msg = d.get("message") or {}
        content = msg.get("content")
        text = _text_of(content)
        if "[Request interrupted by user" in text:
            s.interrupts += 1
            return
        if _has_tool_result(content):
            return
        origin = d.get("origin")
        if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
            return
        if s.is_subagent:
            return  # 子代理的“用户消息”是主代理写的任务说明，不算用户
        m = _CMD.search(text)
        if m:
            name = m.group(1).strip().lstrip("/")
            s.slash[name] += 1
            if name in REVIEW_NAMES:
                s.review_used = True
            if name == "goal":
                s.goal_used = True
            if name == "plan":
                s.plan_used = True
            return
        stripped = text.lstrip()
        if not stripped or stripped.startswith(_SYNTHETIC_PREFIX):
            return
        s.add_user_message(text, parse_ts(d.get("timestamp")))
        pm = d.get("permissionMode")
        if pm:
            s.modes[pm] += 1
            if pm == "plan":
                s.plan_used = True

    def _on_assistant(self, s: SessionStats, d: dict, seen: set) -> None:
        msg = d.get("message") or {}
        mid = msg.get("id") or d.get("requestId")
        model = msg.get("model") or ""
        first = mid not in seen
        if first:
            seen.add(mid)
            if model and model != "<synthetic>":
                s.models[model] += 1
            u = msg.get("usage") or {}
            s.tok_input += int(u.get("input_tokens") or 0)
            s.tok_output += int(u.get("output_tokens") or 0)
            s.tok_cache_read += int(u.get("cache_read_input_tokens") or 0)
            s.tok_cache_write += int(u.get("cache_creation_input_tokens") or 0)
            eff = d.get("effort")
            if isinstance(eff, str):
                s.efforts[eff] += 1
        for c in msg.get("content") or []:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            name = c.get("name") or "?"
            inp = c.get("input") or {}
            cat = tool_category(name)
            s.tools[name] += 1
            s.tool_cats[cat] += 1
            if cat == "edit":
                s.edits += 1
                fp = inp.get("file_path") or inp.get("notebook_path") if isinstance(inp, dict) else None
                if fp is None or is_code_path(fp):
                    s.code_edits += 1
            elif cat == "bash":
                cmd = inp.get("command") if isinstance(inp, dict) else None
                if isinstance(cmd, str):
                    s.add_command(cmd)
            elif cat == "browser" and s.edits:
                s.verify_after_edit = True
            elif cat == "agent":
                s.subagent_calls += 1
                st = str(inp.get("subagent_type") or "") + " " + str(inp.get("description") or "")
                if "review" in st.lower() or "审查" in st:
                    s.review_used = True
            elif cat == "skill":
                sk = str(inp.get("skill") or inp.get("name") or "?").split(":")[-1]
                s.skills[sk] += 1
                if sk in REVIEW_NAMES:
                    s.review_used = True
            elif cat == "plan":
                s.plan_used = True
            elif cat == "ask":
                s.ask_user += 1
            if name.startswith("mcp__"):
                parts = name.split("__")
                if len(parts) >= 3:
                    s.mcp_servers[parts[1]] += 1
            if name in ("EnterWorktree",):
                s.worktree = True

    # ---------- 配置 ----------
    def read_config(self, project_paths: list) -> dict:
        home = self.home
        cfg = {"agent": self.id, "rules": {}, "skills": [], "commands": 0, "plugins": 0,
               "plugin_skills": [], "mcp": {}, "permissions": {}, "hooks": 0, "agents": 0,
               "cleanup_period_days": None, "projects": {}}

        g = self.root / "CLAUDE.md"
        if g.is_file():
            cfg["rules"]["global"] = {"file": "~/.claude/CLAUDE.md", **rule_file_info(g)}
        grules = list((self.root / "rules").glob("*.md")) if (self.root / "rules").is_dir() else []
        if grules:
            cfg["rules"]["global_rules_dir"] = {"files": len(grules), "lines": sum(rule_file_info(p)["lines"] for p in grules)}

        cfg["skills"] = [n for n, _ in list_skills(self.root / "skills")]
        cmd_dir = self.root / "commands"
        cfg["commands"] = len(list(cmd_dir.glob("*.md"))) if cmd_dir.is_dir() else 0
        agents_dir = self.root / "agents"
        cfg["agents"] = len(list(agents_dir.glob("*.md"))) if agents_dir.is_dir() else 0

        settings = load_json(self.root / "settings.json") or {}
        cfg["cleanup_period_days"] = settings.get("cleanupPeriodDays")
        perms = settings.get("permissions") or {}
        cfg["permissions"] = {
            "allow": len(perms.get("allow") or []),
            "deny": len(perms.get("deny") or []),
            "default_mode": perms.get("defaultMode"),
        }
        cfg["hooks"] = _count_hooks(settings.get("hooks"))
        cfg["skill_overrides"] = len(settings.get("skillOverrides") or {})

        # 插件
        installed = load_json(self.root / "plugins" / "installed_plugins.json") or {}
        plugins = installed.get("plugins") if isinstance(installed, dict) else None
        plugin_mcp = Counter()
        if isinstance(plugins, dict):
            enabled = settings.get("enabledPlugins") or {}
            for key, recs in plugins.items():
                if enabled and enabled.get(key) is False:
                    continue
                cfg["plugins"] += 1
                for rec in recs if isinstance(recs, list) else [recs]:
                    ip = Path(rec.get("installPath") or "")
                    if not ip.is_dir():
                        continue
                    cfg["plugin_skills"] += [n for n, _ in list_skills(ip / "skills")]
                    pm = load_json(ip / ".mcp.json") or {}
                    for srv in (pm.get("mcpServers") or pm or {}):
                        if isinstance(srv, str):
                            plugin_mcp[srv] += 1
                    hj = load_json(ip / "hooks" / "hooks.json") or {}
                    cfg["hooks"] += _count_hooks(hj.get("hooks"))
                    break
        cfg["plugin_skills"] = sorted(set(cfg["plugin_skills"]))
        desk = []
        if self.desktop_used:
            for root in self.desktop_plugin_roots():
                desk += [n for n, _ in list_skills(root)]
        cfg["desktop_plugin_skills"] = sorted(set(desk) - set(cfg["plugin_skills"]))

        gj = load_json(self.global_json) or {}
        user_mcp = list((gj.get("mcpServers") or {}).keys())
        cfg["mcp"] = {"user": user_mcp, "plugin": sorted(plugin_mcp), "project": {}}
        cfg["skill_usage_lifetime"] = {k.split(":")[-1]: (v or {}).get("usageCount", 0)
                                       for k, v in (gj.get("skillUsage") or {}).items()}
        gprojects = gj.get("projects") or {}

        # 项目级
        for p in project_paths:
            pp = Path(p)
            info = {"exists": pp.is_dir(), "rule_files": [], "skills": [], "mcp": [],
                    "allow": 0, "hooks": 0, "agents": 0}
            if pp.is_dir():
                for anc in ancestors_until_home(pp, home):
                    for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", "AGENTS.md"):
                        f = anc / name
                        if f.is_file():
                            info["rule_files"].append({"name": name, "depth": len(pp.parts) - len(anc.parts),
                                                       **rule_file_info(f)})
                rd = pp / ".claude" / "rules"
                if rd.is_dir():
                    for f in rd.glob("*.md"):
                        info["rule_files"].append({"name": ".claude/rules/" + f.name, "depth": 0, **rule_file_info(f)})
                info["skills"] = [n for n, _ in list_skills(pp / ".claude" / "skills")]
                mj = load_json(pp / ".mcp.json") or {}
                info["mcp"] = list((mj.get("mcpServers") or {}).keys())
                for sf in ("settings.json", "settings.local.json"):
                    sj = load_json(pp / ".claude" / sf) or {}
                    info["allow"] += len(((sj.get("permissions") or {}).get("allow")) or [])
                    info["hooks"] += _count_hooks(sj.get("hooks"))
                ad = pp / ".claude" / "agents"
                info["agents"] = len(list(ad.glob("*.md"))) if ad.is_dir() else 0
            gp = gprojects.get(p) or {}
            info["allow"] += len(gp.get("allowedTools") or [])
            info["mcp"] += list((gp.get("mcpServers") or {}).keys())
            cfg["projects"][p] = info
        return cfg


def _count_hooks(h) -> int:
    if not isinstance(h, dict):
        return 0
    n = 0
    for groups in h.values():
        if isinstance(groups, list):
            for g in groups:
                hs = g.get("hooks") if isinstance(g, dict) else None
                n += len(hs) if isinstance(hs, list) else 1
    return n
