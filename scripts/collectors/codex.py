"""OpenAI Codex 采集器（CLI、App、IDE 插件共用 $CODEX_HOME，默认 ~/.codex）。

记录位置：sessions/YYYY/MM/DD/rollout-*.jsonl，7 天后压缩为 .jsonl.zst；archived_sessions/ 同格式。
每行 {"timestamp", "type", "payload"}。

原始字段 → 统一统计 的映射（新版优先，旧版兜底）：
  event_msg.item_completed.item.type=UserMessage           → 用户消息（旧版：event_msg.user_message / response_item user message）
  item.type=CommandExecution（command 数组最后一段）      → Shell 命令（旧版：response_item function_call shell/exec_command）
  item.type=FileChange                                     → 改文件（旧版：apply_patch）
  item.type=McpToolCall.server                             → MCP 服务器
  item.type=WebSearch / Extension(kind=web.*)              → 联网
  item.type=SubAgentActivity(kind=started)                 → 子代理
  item.type=ContextCompaction / 顶层 compacted             → 压缩
  turn_context.collaboration_mode.mode=plan                → Plan 模式
  turn_context.approval_policy + sandbox_policy.type       → 权限模式（按轮次）
  turn_context.model / reasoning_effort                    → 模型与推理强度（按轮次）
  event_msg.turn_aborted(reason=interrupted)               → 用户打断
  event_msg.thread_goal_updated                            → 用过 goal
  event_msg.token_count.info.total_token_usage（取最大）   → token
  session_meta.source 为 {"subagent": ...}                 → 子代理会话
解不开的 .zst 改读 state_5.sqlite 的 threads 表，只有会话级数据（level=session）。
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from .base import (
    Collector,
    Detection,
    SessionStats,
    ancestors_until_home,
    dir_size,
    is_code_path,
    list_skills,
    parse_ts,
    read_jsonl,
    rule_file_info,
    sqlite_ro,
    zstd_available,
    zstd_lines,
)

_DATE_IN_NAME = re.compile(r"rollout-(\d{4})-(\d{2})-(\d{2})T")
_INJECTED = ("<environment_context", "# AGENTS.md", "<user_instructions", "<INSTRUCTIONS", "<permissions",
             "<turn_aborted", "<user_shell_command", "<collaboration_mode", "<skill", "<subagent")
_SKILL_PATH = re.compile(r"/([^/\s]+)/SKILL\.md")
_PATCH_FILE = re.compile(r"\*\*\* (?:Add|Update|Delete) File: (\S+)")
_SKILL_MENTION = re.compile(r"(?:^|\s)\$([A-Za-z0-9][\w.-]+)")


def _norm(t) -> str:
    return str(t or "").replace("_", "").lower()


def _user_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for x in content or []:
        if isinstance(x, dict) and x.get("type") in ("text", "input_text"):
            parts.append(x.get("text") or "")
    return "\n".join(parts)


def _cmd_string(cmd) -> str:
    if isinstance(cmd, list):
        return str(cmd[-1]) if cmd else ""
    return str(cmd or "")


class CodexCollector(Collector):
    id = "codex"
    display_name = "Codex"

    def __init__(self, home: Path):
        super().__init__(home)
        base = os.environ.get("CODEX_HOME")
        self.root = Path(base) if base else home / ".codex"
        self.zstd_ok = zstd_available()
        self.degraded_files = 0

    def _session_files(self):
        for sub in ("sessions", "archived_sessions"):
            d = self.root / sub
            if not d.is_dir():
                continue
            for f in d.rglob("rollout-*"):
                if f.name.endswith(".jsonl") or f.name.endswith(".jsonl.zst"):
                    yield f

    # ---------- 探测 ----------
    def detect(self) -> Detection:
        det = Detection(self.id, self.display_name, False)
        if not self.root.is_dir():
            return det
        det.found = True
        det.paths = [str(self.root)]
        files = list(self._session_files())
        zst = sum(1 for f in files if f.name.endswith(".zst"))
        det.size_bytes = dir_size([p for p in (self.root / "sessions", self.root / "archived_sessions") if p.exists()])
        if not files:
            det.level = "config"
            return det
        det.level = "full" if (zst == 0 or self.zstd_ok) else "session"
        det.notes.append("{} 个会话文件，其中 {} 个已压缩为 .zst".format(len(files), zst))
        if zst and not self.zstd_ok:
            det.notes.append("当前 Python 无法解压 .zst（需要 Python 3.14+ 或系统 zstd 命令），压缩的会话只统计会话级数据")
        newest = max(files, key=lambda f: f.stat().st_mtime)
        lines = zstd_lines(newest) if newest.name.endswith(".zst") else read_jsonl(newest)
        for line in lines or []:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "session_meta":
                det.version = (d.get("payload") or {}).get("cli_version") or ""
            break
        return det

    # ---------- 会话 ----------
    def collect(self, since: datetime, until: datetime) -> list:
        out = []
        earliest = (since - timedelta(days=7)).date()
        since_ts = since.timestamp()
        fallback_ids = []
        for f in self._session_files():
            m = _DATE_IN_NAME.search(f.name)
            if m:
                fd = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
                if fd < earliest or fd > until.date():
                    continue
            if f.stat().st_mtime < since_ts:
                continue
            if f.name.endswith(".zst"):
                lines = zstd_lines(f)
                if lines is None:
                    self.degraded_files += 1
                    fallback_ids.append(f)
                    continue
            else:
                lines = read_jsonl(f)
            s = self._parse(f, lines, since, until)
            if s is not None and (s.user_msgs > 0 or s.is_subagent and s.total_lines > 0):
                out.append(s)
        if fallback_ids:
            out += self._from_sqlite(fallback_ids, since, until)
        return out

    def _parse(self, path: Path, lines, since: datetime, until: datetime):
        s = SessionStats(agent=self.id, session_id=path.name.split(".")[0])
        users_item, users_event, users_resp = [], [], []
        cmds_item, cmds_resp = [], []
        edits_item = edits_resp = 0
        code_item = code_resp = 0
        subagent_started = collab_calls = 0
        compact_items = compact_records = 0
        tok = {}
        for line in lines:
            try:
                d = json.loads(line)
            except ValueError:
                s.unknown_lines += 1
                continue
            t = d.get("type")
            p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            ts = parse_ts(d.get("timestamp"))
            if t == "session_meta":
                src = p.get("source")
                s.is_subagent = isinstance(src, dict) and "subagent" in src
                s.entrypoint = p.get("originator") or (src if isinstance(src, str) else "subagent")
                s.automated = src == "exec" or any(k in str(p.get("originator") or "").lower() for k in ("exec", "canvas", "sdk"))
                s.version = p.get("cli_version") or ""
                s.project_path = p.get("cwd") or ""
                s.session_id = p.get("id") or s.session_id
                continue
            if ts is not None and (ts < since or ts > until):
                continue
            s.total_lines += 1
            s.touch(ts)
            pt = p.get("type")
            if t == "turn_context":
                model = p.get("model") or ((p.get("collaboration_mode") or {}).get("settings") or {}).get("model")
                if model:
                    s.models[model] += 1
                cm = p.get("collaboration_mode") or {}
                eff = p.get("effort") or (cm.get("settings") or {}).get("reasoning_effort")
                if eff:
                    s.efforts[str(eff)] += 1
                if str(cm.get("mode") or "").lower() == "plan":
                    s.plan_used = True
                sb = p.get("sandbox_policy")
                sbt = sb.get("type") if isinstance(sb, dict) else sb
                s.modes["{}/{}".format(p.get("approval_policy") or "?", sbt or "?")] += 1
                if p.get("cwd") and not s.project_path:
                    s.project_path = p["cwd"]
            elif t == "compacted":
                compact_records += 1
            elif t == "event_msg":
                if pt == "item_completed":
                    it = p.get("item") or {}
                    k = _norm(it.get("type"))
                    if k == "usermessage":
                        users_item.append((_user_text(it.get("content")), ts))
                    elif k == "commandexecution":
                        cmds_item.append(it)
                    elif k == "filechange":
                        ch = it.get("changes")
                        edits_item += len(ch) if isinstance(ch, dict) else 1
                        code_item += sum(1 for k in ch if is_code_path(k)) if isinstance(ch, dict) else 1
                    elif k == "mcptoolcall":
                        srv = str(it.get("server") or "?")
                        s.mcp_servers[srv] += 1
                        low = srv.lower() + " " + str(it.get("tool") or "").lower()
                        cat = "browser" if any(x in low for x in ("browser", "chrome", "playwright", "computer")) else "mcp"
                        s.tool_cats[cat] += 1
                        s.tools["mcp:" + srv] += 1
                        if cat == "browser" and (edits_item or edits_resp):
                            s.verify_after_edit = True
                    elif k == "websearch" or (k == "extension" and str(it.get("kind") or "").startswith("web")):
                        s.tool_cats["web"] += 1
                    elif k == "subagentactivity":
                        if it.get("kind") == "started":
                            subagent_started += 1
                            if "review" in str(it.get("agent_path") or "").lower():
                                s.review_used = True
                    elif k == "collabagenttoolcall":
                        collab_calls += 1
                    elif k == "contextcompaction":
                        compact_items += 1
                    elif k == "imageview":
                        s.tool_cats["read"] += 1
                    elif "review" in k:
                        s.review_used = True
                elif pt == "user_message":
                    users_event.append((str(p.get("message") or ""), ts))
                elif pt == "turn_aborted":
                    if str(p.get("reason") or "") in ("interrupted", "user_interrupted"):
                        s.interrupts += 1
                elif pt == "thread_goal_updated":
                    s.goal_used = True
                elif pt == "token_count":
                    info = p.get("info") or {}
                    tot = info.get("total_token_usage") or {}
                    if (tot.get("total_tokens") or 0) >= (tok.get("total_tokens") or 0):
                        tok = tot
                elif pt and "review" in pt:
                    s.review_used = True
                elif pt == "error":
                    msg = str(p.get("message") or "").lower()
                    s.errors["rate_limit" if ("rate" in msg or "429" in msg) else "other"] += 1
            elif t == "response_item":
                if pt == "message" and p.get("role") == "user":
                    users_resp.append((_user_text(p.get("content")), ts))
                elif pt in ("function_call", "custom_tool_call", "local_shell_call"):
                    name = str(p.get("name") or pt)
                    if name in ("shell", "exec_command", "local_shell", "container.exec") or pt == "local_shell_call":
                        args = p.get("arguments") or p.get("action") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except ValueError:
                                args = {"cmd": args}
                        cmds_resp.append({"command": args.get("command") or args.get("cmd") or ""})
                    elif name == "apply_patch":
                        edits_resp += 1
                        files = _PATCH_FILE.findall(str(p.get("input") or p.get("arguments") or ""))
                        code_resp += sum(1 for f in files if is_code_path(f)) if files else 1
        # 选用最完整的一套
        users = users_item or users_event or [u for u in users_resp if not u[0].lstrip().startswith(_INJECTED)]
        for u, uts in users:
            st = u.lstrip()
            if not st or st.startswith(_INJECTED):
                continue
            s.add_user_message(u, uts)
            for sk in _SKILL_MENTION.findall(u):
                s.skills[sk] += 1
        s.edits = edits_item or edits_resp
        s.code_edits = code_item if edits_item else code_resp
        cmds = cmds_item or cmds_resp
        for c in cmds:
            cs = _cmd_string(c.get("command"))
            s.tool_cats["bash"] += 1
            s.tools["shell"] += 1
            s.add_command(cs)
            for pc in c.get("parsed_cmd") or []:
                path = str(pc.get("path") or pc.get("cmd") or "")
                m = _SKILL_PATH.search(path)
                if m:
                    s.skills[m.group(1)] += 1
            if not c.get("parsed_cmd"):
                m = _SKILL_PATH.search(cs)
                if m:
                    s.skills[m.group(1)] += 1
        if s.edits:
            s.tool_cats["edit"] += s.edits
            if any(f in ("test", "lint", "build") for f in s.cmd_families):
                s.verify_after_edit = True
        s.subagent_calls = subagent_started or collab_calls
        if s.subagent_calls:
            s.tool_cats["agent"] += s.subagent_calls
        s.compact_auto = max(compact_items, compact_records)
        if tok:
            cached = int(tok.get("cached_input_tokens") or 0)
            s.tok_input = max(0, int(tok.get("input_tokens") or 0) - cached)
            s.tok_cache_read = cached
            s.tok_cache_write = int(tok.get("cache_write_input_tokens") or 0)
            s.tok_output = int(tok.get("output_tokens") or 0)
        if s.project_path and "/worktrees/" in s.project_path:
            s.worktree = True
        return s

    def _from_sqlite(self, files: list, since: datetime, until: datetime) -> list:
        con = sqlite_ro(self.root / "state_5.sqlite")
        if con is None:
            return []
        out = []
        wanted = {str(f) for f in files}
        try:
            rows = con.execute(
                "select id, rollout_path, created_at, updated_at, source, cwd, approval_mode, sandbox_policy, "
                "tokens_used, model, reasoning_effort, cli_version, originator from threads").fetchall()
        except Exception:
            con.close()
            return []
        con.close()
        for r in rows:
            (tid, rp, created, updated, source, cwd, appr, sandbox, tokens, model, eff, ver, orig) = r
            if rp not in wanted:
                continue
            st, en = parse_ts(created), parse_ts(updated)
            if en is None or en < since or (st and st > until):
                continue
            s = SessionStats(agent=self.id, session_id=tid, level="session")
            s.start, s.end = st, en
            s.is_subagent = str(source or "").startswith("{")
            s.entrypoint = orig or str(source or "")
            s.project_path = cwd or ""
            s.version = ver or ""
            if model:
                s.models[model] += 1
            if eff:
                s.efforts[eff] += 1
            try:
                sbt = json.loads(sandbox).get("type") if sandbox and sandbox.startswith("{") else sandbox
            except ValueError:
                sbt = sandbox
            s.modes["{}/{}".format(appr or "?", sbt or "?")] += 1
            s.tok_output = 0
            s.tok_input = int(tokens or 0)
            s.user_msgs = 1  # 只知道会话存在，消息数未知
            out.append(s)
        return out

    # ---------- 配置 ----------
    def read_config(self, project_paths: list) -> dict:
        cfg = {"agent": self.id, "rules": {}, "skills": [], "plugins": 0, "mcp": {}, "permissions": {},
               "hooks": 0, "projects": {}, "project_doc_max_bytes": 32768}
        for name in ("AGENTS.md", "AGENTS.override.md"):
            f = self.root / name
            if f.is_file():
                cfg["rules"]["global" if name == "AGENTS.md" else "global_override"] = {
                    "file": "~/.codex/" + name, **rule_file_info(f)}
        conf = _load_toml(self.root / "config.toml")
        cfg["project_doc_max_bytes"] = int(conf.get("project_doc_max_bytes") or 32768)
        cfg["permissions"] = {
            "approval_policy": conf.get("approval_policy"),
            "sandbox_mode": conf.get("sandbox_mode"),
            "rules_files": 0,
            "rules_lines": 0,
        }
        rd = self.root / "rules"
        if rd.is_dir():
            files = list(rd.glob("*.rules"))
            cfg["permissions"]["rules_files"] = len(files)
            cfg["permissions"]["rules_lines"] = sum(rule_file_info(f)["lines"] for f in files)
        cfg["mcp"] = {"user": sorted((conf.get("mcp_servers") or {}).keys()), "project": {}}
        plugins = conf.get("plugins") or {}
        cfg["plugins"] = sum(1 for v in plugins.values() if not (isinstance(v, dict) and v.get("enabled") is False))
        hooks = conf.get("hooks") or {}
        n = 0
        for k, v in hooks.items():
            n += len(v) if (k == "state" and isinstance(v, dict)) else (len(v) if isinstance(v, list) else 1)
        hj = self.root / "hooks.json"
        if hj.is_file():
            try:
                n += sum(len(v) if isinstance(v, list) else 1 for v in (json.loads(hj.read_text()).get("hooks") or {}).values())
            except (ValueError, OSError, AttributeError):
                pass
        cfg["hooks"] = n
        names = []
        for root in (self.home / ".agents" / "skills", self.root / "skills"):
            names += [n for n, _ in list_skills(root)]
        cfg["skills"] = sorted(set(names))
        for p in project_paths:
            pp = Path(p)
            info = {"exists": pp.is_dir(), "rule_files": [], "skills": [], "mcp": []}
            if pp.is_dir():
                for anc in ancestors_until_home(pp, self.home):
                    for name in ("AGENTS.override.md", "AGENTS.md"):
                        f = anc / name
                        if f.is_file():
                            info["rule_files"].append({"name": name, "depth": len(pp.parts) - len(anc.parts),
                                                       **rule_file_info(f)})
                info["skills"] = [n for n, _ in list_skills(pp / ".agents" / "skills")]
                pc = _load_toml(pp / ".codex" / "config.toml")
                info["mcp"] = sorted((pc.get("mcp_servers") or {}).keys())
            cfg["projects"][p] = info
        return cfg


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        import tomllib  # type: ignore

        with open(path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        return _mini_toml(path)
    except Exception:
        return _mini_toml(path)


def _mini_toml(path: Path) -> dict:
    """Python 3.9/3.10 没有 tomllib：只解析我们需要的顶层标量和表名。"""
    out: dict = {}
    cur = out
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip() if not raw.strip().startswith("[") else raw.strip()
        if not line:
            continue
        m = re.match(r"^\[\[?([^\]]+)\]\]?$", line)
        if m:
            parts = [x.strip().strip('"') for x in re.findall(r'"[^"]*"|[^.]+', m.group(1))]
            cur = out
            for part in parts:
                cur = cur.setdefault(part, {}) if isinstance(cur, dict) else {}
            continue
        m = re.match(r'^([A-Za-z0-9_."-]+)\s*=\s*(.+)$', line)
        if m and isinstance(cur, dict):
            k, v = m.group(1).strip('"'), m.group(2).strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            elif v in ("true", "false"):
                v = v == "true"
            elif re.match(r"^-?\d+$", v):
                v = int(v)
            cur[k] = v
    return out
