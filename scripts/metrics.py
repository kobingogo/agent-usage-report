"""把各采集器的会话统计汇总成 facts（只有数字和脱敏后的少量例子）。"""
from __future__ import annotations

import platform
import re
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from collectors.base import list_skills, model_tier
from redact import project_key, project_label, redact

TOOL_VERSION = "0.1.0"

# 各产品的 Skill 目录（用于装用比和重复安装统计）
SKILL_DIRS = {
    "claude_code": [".claude/skills"],
    "codex": [".agents/skills", ".codex/skills"],
    "cursor": [".cursor/skills"],
    "_other": [".pi/agent/skills", ".gemini/skills", ".config/opencode/skills"],
}


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def _median(xs):
    return statistics.median(xs) if xs else 0


def _p90(xs):
    if not xs:
        return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]


def max_concurrency(bucket_sets):
    """同一个 30 分钟时间片里都有消息的会话数，取最大值。会话开着不说话不算并行。"""
    c = Counter()
    for bs in bucket_sets:
        c.update(bs)
    return max(c.values()) if c else 0


def _parallel_slots(bucket_sets):
    c = Counter()
    for bs in bucket_sets:
        c.update(bs)
    return sum(1 for v in c.values() if v > 1)


def skill_inventory(home: Path, configs: dict) -> dict:
    """返回 {alias: 规范名}、每个目录的 Skill 数、去重后的总数和重复项。"""
    alias = {}
    per_dir = {}
    where = {}
    for agent, rels in SKILL_DIRS.items():
        for rel in rels:
            items = list_skills(home / rel)
            if not items:
                continue
            per_dir["~/" + rel] = len(items)
            for name, path in items:
                alias[Path(path).name] = name
                alias[name] = name
                where.setdefault(name, set()).add("~/" + rel)
    cc = configs.get("claude_code") or {}
    for key, label in (("plugin_skills", "Claude Code 插件"), ("desktop_plugin_skills", "Claude 桌面 App 插件")):
        for n in cc.get(key) or []:
            alias.setdefault(n, n)
            where.setdefault(n, set()).add(label)
            if label not in per_dir:
                per_dir[label] = 0
            per_dir[label] += 1
    dups = sorted(((n, len(w)) for n, w in where.items() if len(w) > 1), key=lambda x: -x[1])
    return {
        "alias": alias,
        "per_dir": per_dir,
        "unique": len(where),
        "duplicates": [{"name": n, "copies": c} for n, c in dups],
        "duplicate_count": len(dups),
    }


# 应用自动建的临时目录：不当作“项目”
_AUTO_DIRS = re.compile(r"(/Documents/Codex/\d{4}-\d{2}-\d{2}/|/scratch-workspaces/|^/tmp/|^/private/tmp/|^/private/var/|^/var/folders/)")
ACTIVE_MIN_SESSIONS = 2
ACTIVE_MIN_MESSAGES = 10


def is_active_project(path: str, sessions: int, messages: int) -> bool:
    if not path or _AUTO_DIRS.search(path):
        return False
    return sessions >= ACTIVE_MIN_SESSIONS or messages >= ACTIVE_MIN_MESSAGES


def build_facts(home: Path, detections: dict, sessions_by_agent: dict, configs: dict,
                since: datetime, until: datetime, salt: str):
    """返回 (facts, private)。private 只含项目真名映射，只留在本机、只用于 --show-projects 和分享卡安全检查。"""
    inv = skill_inventory(home, configs)
    alias = inv["alias"]

    # 先给项目统一编号（跨 Agent 一致），按消息数排序
    project_msgs, project_sessions = Counter(), Counter()
    per_agent_proj = {}
    for agent_id, ss in sessions_by_agent.items():
        pa = {}
        for s in ss:
            if s.is_subagent or s.automated or not s.project_path:
                continue
            project_msgs[s.project_path] += s.user_msgs
            project_sessions[s.project_path] += 1
            m, n = pa.get(s.project_path, (0, 0))
            pa[s.project_path] = (m + 1, n + s.user_msgs)
        per_agent_proj[agent_id] = pa
    ordered = [p for p, _ in project_msgs.most_common()]
    labels = {p: project_label(i) for i, p in enumerate(ordered)}

    all_main = []
    agents = {}
    for agent_id, det in detections.items():
        ss = sessions_by_agent.get(agent_id) or []
        main = [s for s in ss if not s.is_subagent and not s.automated]
        auto = [s for s in ss if not s.is_subagent and s.automated]
        subs = [s for s in ss if s.is_subagent]
        full = [s for s in main if s.level == "full"]
        all_main += main
        agents[agent_id] = _agent_facts(agent_id, det, main, subs, full, auto, configs.get(agent_id) or {},
                                        alias, labels, per_agent_proj.get(agent_id) or {}, since, until)

    private = {"project_names": {labels[p]: Path(p).name for p in ordered}}
    projects = [{
        "key": project_key(p, salt),
        "label": labels[p],
        "sessions": project_sessions[p],
        "messages": project_msgs[p],
        "active": is_active_project(p, project_sessions[p], project_msgs[p]),
    } for p in ordered if is_active_project(p, project_sessions[p], project_msgs[p]) or p in ordered[:10]]

    starts = [s.start for s in all_main if s.start]
    ends = [s.end for s in all_main if s.end]
    short = Counter()
    for s in all_main:
        short.update(s.short_texts)
    examples = []
    for text, n in short.most_common(30):
        r = redact(text)
        if n >= 2 and r.strip() and r not in [e["text"] for e in examples]:
            examples.append({"text": r, "count": n})
        if len(examples) >= 6:
            break

    facts = {
        "meta": {
            "tool_version": TOOL_VERSION,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "python": platform.python_version(),
            "platform": sys.platform,
            "window": {
                "since": since.date().isoformat(),
                "until": until.date().isoformat(),
                "days": max(1, (until - since).days),
                "first_activity": min(starts).astimezone().date().isoformat() if starts else None,
                "last_activity": max(ends).astimezone().date().isoformat() if ends else None,
            },
        },
        "totals": {
            "sessions": len(all_main),
            "user_messages": sum(s.user_msgs for s in all_main if s.level == "full"),
            "agents_with_sessions": sum(1 for a in agents.values() if a["sessions"] > 0),
            "projects": len(ordered),
            "active_projects": sum(1 for p in ordered if is_active_project(p, project_sessions[p], project_msgs[p])),
            "automated_sessions": sum(a["sessions_automated"] for a in agents.values()),
        },
        "agents": agents,
        "skills_inventory": {k: v for k, v in inv.items() if k != "alias"},
        "projects": projects,
        "short_examples": examples,
    }
    return facts, private


def _local_date(dt):
    return dt.astimezone().date().isoformat() if dt else None


def _session_brief(s, labels):
    hours = round((s.end - s.start).total_seconds() / 3600.0, 1) if s.start and s.end else 0
    return {
        "project": labels.get(s.project_path, "未归属"),
        "date": _local_date(s.start),
        "messages": s.user_msgs,
        "hours": hours,
        "compactions": s.compact_auto + s.compact_manual,
        "code_edit": s.code_edits > 0,
        "verified": s.verify_after_edit,
    }


def _agent_facts(agent_id, det, main, subs, full, auto, cfg, alias, labels, proj_activity, since, until) -> dict:
    msgs_per_session = [s.user_msgs for s in full]
    chars = [c for s in full for c in s.user_chars]
    user_msgs = sum(s.user_msgs for s in full)
    slash = Counter()
    tools = Counter()
    cats = Counter()
    skills = Counter()
    mcp = Counter()
    fam = Counter()
    modes = Counter()
    models = Counter()
    efforts = Counter()
    errors = Counter()
    entry = Counter()
    versions = Counter()
    days = Counter()
    hours = Counter()
    for s in main:
        slash.update(s.slash)
        tools.update(s.tools)
        cats.update(s.tool_cats)
        for k, v in s.skills.items():
            skills[alias.get(k, k)] += v
        mcp.update(s.mcp_servers)
        fam.update(s.cmd_families)
        modes.update(s.modes)
        models.update(s.models)
        efforts.update(s.efforts)
        errors.update(s.errors)
        entry[s.entrypoint] += 1
        days.update(s.msg_days)
        hours.update(s.msg_hours)
        if s.version:
            versions[s.version] += 1
    for s in subs:  # 子代理里调用的 Skill、MCP 也算“用过”
        for k, v in s.skills.items():
            skills[alias.get(k, k)] += v
        mcp.update(s.mcp_servers)

    tok = {
        "input": sum(s.tok_input for s in main + subs),
        "output": sum(s.tok_output for s in main + subs),
        "cache_read": sum(s.tok_cache_read for s in main + subs),
        "cache_write": sum(s.tok_cache_write for s in main + subs),
    }
    denom = tok["input"] + tok["cache_read"] + tok["cache_write"]
    tiers = Counter()
    for m, n in models.items():
        tiers[model_tier(m)] += n
    edit_sessions = [s for s in full if s.code_edits > 0]  # 只算改过代码的会话；纯写文档的不要求跑测试
    long_sessions = [s for s in full if s.user_msgs > 40]
    total_lines = sum(s.total_lines for s in main + subs)
    unknown = sum(s.unknown_lines for s in main + subs)

    # 证据：具体是哪几个会话
    by_len = sorted(full, key=lambda s: -s.user_msgs)
    by_comp = sorted([s for s in main if s.compact_auto], key=lambda s: -s.compact_auto)
    comp_total = sum(s.compact_auto for s in main)
    top_comp = by_comp[:5]
    multi_day = [s for s in by_comp if s.start and s.end and (s.end - s.start).total_seconds() > 86400]
    unverified = sorted([s for s in edit_sessions if not s.verify_after_edit], key=lambda s: -s.user_msgs)
    evidence = {
        "longest": [_session_brief(s, labels) for s in by_len[:3]],
        "compaction_top": [_session_brief(s, labels) for s in top_comp],
        "compaction_top_share": _pct(sum(s.compact_auto for s in top_comp), comp_total),
        "compaction_multi_day_sessions": len(multi_day),
        "compaction_multi_day_count": sum(s.compact_auto for s in multi_day),
        "unverified_code_sessions": [_session_brief(s, labels) for s in unverified[:3]],
    }

    # 每天的消息数（窗口内每一天都给一个值）
    series = []
    d = since.astimezone().date()
    end = until.astimezone().date()
    while d <= end:
        series.append(days.get(d.isoformat(), 0))
        d = d.fromordinal(d.toordinal() + 1)

    behavior = {
        "clear": slash.get("clear", 0) + slash.get("new", 0),
        "compact_manual": sum(s.compact_manual for s in main) + slash.get("compact", 0),
        "compact_auto": comp_total,
        "subagent_calls": sum(s.subagent_calls for s in main),
        "subagent_sessions": len(subs),
        "sessions_with_subagent": sum(1 for s in main if s.subagent_calls),
        "plan_sessions": sum(1 for s in main if s.plan_used),
        "goal_sessions": sum(1 for s in main if s.goal_used),
        "btw": slash.get("btw", 0),
        "rewind": slash.get("rewind", 0) + slash.get("undo", 0),
        "interrupts": sum(s.interrupts for s in main),
        "ask_user": sum(s.ask_user for s in main),
        "review_sessions": sum(1 for s in main if s.review_used),
        "worktree_sessions": sum(1 for s in main if s.worktree),
        "max_parallel": max_concurrency([s.active_buckets for s in main]),
        "parallel_slots": _parallel_slots([s.active_buckets for s in main]),
        "edit_sessions": len(edit_sessions),
        "doc_only_sessions": sum(1 for s in full if s.edits > 0 and s.code_edits == 0),
        "verify_sessions": sum(1 for s in edit_sessions if s.verify_after_edit),
        "long_sessions": len(long_sessions),
        "neg_loop_sessions": sum(1 for s in full if s.neg_loops),
        "continue_msgs": sum(v for s in full for k, v in s.short_texts.items()
                             if k.strip().lower() in ("继续", "continue", "go on", "接着", "继续吧", "go", "继续。")),
        "reads_per_session": round(sum(s.tool_cats.get("read", 0) for s in full) / len(full), 1) if full else 0,
        "skill_calls": sum(skills.values()),
        "mcp_calls": sum(mcp.values()),
    }

    used_mcp = set(mcp)
    return {
        "id": agent_id,
        "name": det.display_name,
        "found": det.found,
        "level": det.level if main or det.level == "config" else ("config" if det.found else "none"),
        "version": det.version or (versions.most_common(1)[0][0] if versions else ""),
        "notes": det.notes,
        "sessions": len(main),
        "sessions_full": len(full),
        "sessions_degraded": len(main) - len(full),
        "sessions_automated": len(auto),
        "entrypoints": dict(entry),
        "data_quality": {"lines": total_lines, "unknown": unknown,
                         "known_pct": _pct(total_lines, total_lines + unknown) if total_lines else None},
        "messages": {
            "total": user_msgs,
            "median_chars": _median(chars),
            "short": sum(s.short_msgs for s in full),
            "short_pct": _pct(sum(s.short_msgs for s in full), user_msgs),
            "file_ref_pct": _pct(sum(s.file_ref_msgs for s in full), user_msgs),
            "per_session_median": _median(msgs_per_session),
            "per_session_p90": _p90(msgs_per_session),
            "per_session_max": max(msgs_per_session) if msgs_per_session else 0,
        },
        "behavior": behavior,
        "evidence": evidence,
        "daily_messages": series,
        "hourly_messages": [hours.get(h, 0) for h in range(24)],
        "slash": dict(slash.most_common(30)),
        "tool_categories": dict(cats),
        "top_tools": dict(tools.most_common(12)),
        "skills_used": dict(skills.most_common(30)),
        "mcp_used": dict(mcp.most_common(20)),
        "command_families": dict(fam),
        "modes": dict(modes),
        "models": dict(models.most_common(8)),
        "model_tiers": dict(tiers),
        "efforts": dict(efforts),
        "tokens": tok,
        "cache_hit_pct": _pct(tok["cache_read"], denom),
        "errors": dict(errors),
        "config": _config_facts(agent_id, cfg, set(skills), used_mcp, labels, proj_activity),
    }


def _config_facts(agent_id, cfg, used_skills: set, used_mcp: set, labels: dict, proj_activity: dict) -> dict:
    if not cfg:
        return {}
    projects = cfg.get("projects") or {}
    covered = existing = 0
    max_lines = 0
    secrets = 0
    chain_bytes_max = 0
    uncovered = []
    covered_list = []
    for p, info in projects.items():
        files = info.get("rule_files") or []
        lines = [f.get("lines", 0) for f in files]
        max_lines = max([max_lines] + lines)
        secrets += sum(f.get("secrets", 0) for f in files)
        chain_bytes_max = max(chain_bytes_max, sum(f.get("bytes", 0) for f in files))
        if not info.get("exists", True):
            continue
        sess, msgs = proj_activity.get(p, (0, 0))
        if proj_activity and not is_active_project(p, sess, msgs):
            continue  # 只看常用项目；一两条消息的临时目录不算
        existing += 1
        row = {"label": labels.get(p, "项目 ?"), "sessions": sess, "messages": msgs,
               "files": [{"name": f["name"], "lines": f["lines"]} for f in files]}
        if files:
            covered += 1
            covered_list.append(row)
        else:
            uncovered.append(row)
    uncovered.sort(key=lambda r: -r["messages"])
    for key, g in (cfg.get("rules") or {}).items():
        # 规则目录记的是总行数，单文件长度看 max_lines
        single = g.get("max_lines", 0) if key == "global_rules_dir" else g.get("lines", 0)
        max_lines = max(max_lines, single or 0)
        secrets += g.get("secrets", 0)

    installed = list(cfg.get("skills") or []) + list(cfg.get("plugin_skills") or []) + list(cfg.get("desktop_plugin_skills") or [])
    for info in projects.values():
        installed += info.get("skills") or []
    installed_set = set(installed)
    mcp = cfg.get("mcp") or {}
    configured = set(mcp.get("user") or []) | set(mcp.get("plugin") or [])
    for info in projects.values():
        configured |= set(info.get("mcp") or [])
    perms = dict(cfg.get("permissions") or {})
    allow_total = perms.get("allow", 0) or 0
    for info in projects.values():
        allow_total += info.get("allow", 0) or 0
    used_installed = used_skills & installed_set if installed_set else used_skills
    return {
        "global_rules": {k: {kk: vv for kk, vv in v.items() if kk != "secrets"} for k, v in (cfg.get("rules") or {}).items()},
        "project_rules": {"projects": existing, "covered": covered, "coverage_pct": _pct(covered, existing),
                          "max_lines": max_lines, "max_chain_bytes": chain_bytes_max,
                          "uncovered": uncovered[:8], "covered_list": covered_list[:8]},
        "secrets_found": secrets,
        "skills_installed": len(installed_set),
        "skills_personal": len(set(cfg.get("skills") or [])),
        "skills_plugin": len(set(cfg.get("plugin_skills") or [])) + len(set(cfg.get("desktop_plugin_skills") or [])),
        "skills_desktop_plugin": len(set(cfg.get("desktop_plugin_skills") or [])),
        "skills_used": len(used_installed),
        "skills_used_names": sorted(used_installed)[:30],
        "skills_never_used": len(installed_set - used_skills),
        "mcp_configured": sorted(configured),
        "mcp_unused": sorted(configured - used_mcp),
        "permissions": perms,
        "allow_rules_total": allow_total,
        "hooks": cfg.get("hooks", 0),
        "plugins": cfg.get("plugins", 0),
        "subagent_defs": cfg.get("agents", 0),
        "commands": cfg.get("commands", 0),
        "skill_overrides": cfg.get("skill_overrides", 0),
        "project_doc_max_bytes": cfg.get("project_doc_max_bytes"),
        "cleanup_period_days": cfg.get("cleanup_period_days"),
    }
