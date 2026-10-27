#!/usr/bin/env python3
"""Agent 使用体检：本机统计 → 打分 → 出报告。只读你的会话记录，不联网，不改任何配置。

用法：
  python3 scan.py detect                 # 看本机有哪些 Agent、数据量多大
  python3 scan.py run [--days 30]        # 统计 + 打分 + 生成报告（默认文字）
  python3 scan.py run --retest           # 复测：只统计上次体检之后的记录，并和上次对比
  python3 scan.py render --narrative narrative.json [--show-projects]
                                         # 用模型写的总评重新渲染报告和分享卡
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from collectors import ALL  # noqa: E402
from metrics import TOOL_VERSION, build_facts  # noqa: E402
import render  # noqa: E402
import score as scoring  # noqa: E402

CHECKS = HERE.parent / "checks" / "checks.json"


def data_dir(arg) -> Path:
    d = Path(arg or os.environ.get("AGENT_USAGE_REPORT_HOME") or (Path.home() / ".agent-usage-report")).expanduser()
    (d / "latest").mkdir(parents=True, exist_ok=True)
    (d / "history").mkdir(parents=True, exist_ok=True)
    return d


def get_salt(d: Path) -> str:
    p = d / "salt"
    if p.exists():
        return p.read_text().strip()
    s = secrets.token_hex(16)
    p.write_text(s)
    return s


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def latest_history(d: Path):
    files = sorted((d / "history").glob("*.json"))
    return (files[-1], read_json(files[-1])) if files else (None, None)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------- 命令 ----------

def cmd_detect(args) -> int:
    home = Path(args.home).expanduser() if args.home else Path.home()
    out = []
    for C in ALL:
        d = C(home).detect()
        out.append({"agent": d.agent, "name": d.display_name, "found": d.found, "level": d.level,
                    "version": d.version, "size_mb": round(d.size_bytes / 1e6, 1), "notes": d.notes})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args) -> int:
    t0 = time.time()
    home = Path(args.home).expanduser() if args.home else Path.home()
    d = data_dir(args.out)
    salt = get_salt(d)
    until = datetime.now(timezone.utc)
    prev_path, prev = latest_history(d)
    if args.retest:
        if not prev:
            log("没有找到上一次体检记录，改为统计最近 {} 天。".format(args.days))
            since = until - timedelta(days=args.days)
        else:
            since = datetime.fromisoformat(prev["generated_at"]).astimezone(timezone.utc)
    elif args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    else:
        since = until - timedelta(days=args.days)
    wanted = set(args.agents.split(",")) if args.agents else None

    detections, sessions, configs = {}, {}, {}
    collectors = []
    for C in ALL:
        if wanted and C.id not in wanted:
            continue
        c = C(home)
        det = c.detect()
        detections[c.id] = det
        collectors.append(c)
        if det.found and det.level in ("full", "session"):
            log("· 统计 {} …".format(det.display_name))
            try:
                sessions[c.id] = c.collect(since, until)
            except Exception as e:  # 一个采集器出错不影响其他
                det.notes.append("统计出错，已跳过：{}".format(type(e).__name__))
                sessions[c.id] = []
    all_paths = sorted({s.project_path for ss in sessions.values() for s in ss if s.project_path and not s.is_subagent})
    for c in collectors:
        if not detections[c.id].found:
            continue
        paths = sorted({s.project_path for s in sessions.get(c.id, []) if s.project_path and not s.is_subagent}) or (
            all_paths if c.id == "cursor" else [])
        try:
            configs[c.id] = c.read_config(paths)
        except Exception as e:
            detections[c.id].notes.append("读取配置出错：{}".format(type(e).__name__))
            configs[c.id] = {}

    facts, private = build_facts(home, detections, sessions, configs, since, until, salt)
    try:
        private["user"] = getpass.getuser()
    except Exception:
        private["user"] = ""
    checks = scoring.load_checks(CHECKS)
    scored = scoring.score(facts, checks)
    summary = scoring.summary_for_history(facts, scored)
    # 只有复测，或上次体检至少隔了一天，才做前后对比；同一天反复运行不算复测
    diff = None
    if prev:
        age_h = (datetime.now().astimezone() - datetime.fromisoformat(prev["generated_at"])).total_seconds() / 3600
        if args.retest or age_h >= 20:
            diff = scoring.diff(prev, summary)

    latest = d / "latest"
    write_json(latest / "facts.json", facts)
    write_json(latest / "findings.json", findings_for_model(scored, checks, diff, facts))
    write_json(latest / "scored.json", scored)
    write_json(latest / "private.json", private)
    if diff:
        write_json(latest / "diff.json", diff)
    elif (latest / "diff.json").exists():
        (latest / "diff.json").unlink()
    narr_path = latest / "narrative.json"
    if narr_path.exists():
        narr_path.unlink()  # 旧的总评不能配新的数字
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    write_json(d / "history" / (stamp + ".json"), summary)

    res = do_render(d, show_projects=args.show_projects)
    took = round(time.time() - t0, 1)
    print(json.dumps({
        "ok": True,
        "seconds": took,
        "window": facts["meta"]["window"],
        "sessions": facts["totals"]["sessions"],
        "user_messages": facts["totals"]["user_messages"],
        "total_score": scored["total"],
        "grade": scored["grade"],
        "counts": scored["counts"],
        "compared_with": prev_path.name if diff else None,
        "files": {
            "findings": str(latest / "findings.json"),
            "facts": str(latest / "facts.json"),
            "report": res["report"],
            "cards": res["cards"],
        },
        "next": "读 findings.json，按 SKILL.md 的格式写 narrative.json 放到同一目录，然后运行 render --narrative 重新出报告。",
    }, ensure_ascii=False, indent=2))
    return 0


def findings_for_model(scored, checks, diff, facts) -> dict:
    """给模型看的精简版：只有判定、数值、默认发现句和处方，不含原始记录。"""
    meta = {c["id"]: c for c in checks["checks"]}
    items = []
    for r in scored["checks"]:
        needs_fix = r["overall"] in ("bad", "unused", "info")
        items.append({
            "id": r["id"],
            "title": r["title"],
            "section": checks["sections"][r["section"]]["title"],
            "overall": r["overall"],
            "agents": {a: {"verdict": x["verdict"], "value": x["value"], "finding": x["finding"],
                           "evidence": x.get("evidence") or []} for a, x in r["per_agent"].items()},
            "rewritable": len(r["per_agent"]) == 1,
            "rx": {a: rx for a, rx in (meta[r["id"]].get("rx") or {}).items() if a in r["per_agent"]} if needs_fix else None,
            "retest": meta[r["id"]].get("retest") if needs_fix else None,
        })
    actions = [{"rank": i + 1, "id": a["id"], "title": a["title"], "problem": meta[a["id"]].get("problem"), "agent": a["agent"],
                "steps": [{"kind": rx["kind"], "text": rx["text"]} for rx in a["rx"]]}
               for i, a in enumerate(render.pick_actions(scored, checks, facts))]
    return {
        "window": facts["meta"]["window"],
        "totals": facts["totals"],
        "agents": {a: {"name": x["name"], "sessions": x["sessions"], "level": x["level"]} for a, x in facts["agents"].items() if x["found"]},
        "total_score": scored["total"],
        "grade": scored["grade"],
        "sections": scored["sections"],
        "counts": scored["counts"],
        "how_to_read": "overall 取各 Agent 里最差的判定（用错了 > 没用上 > 做对了）；分数按会话数加权。actions 已按“影响 × 省事 × 安全优先”排好序。",
        "actions": actions,
        "checks": items,
        "diff": diff,
    }


def do_render(d: Path, narrative_path=None, show_projects=False) -> dict:
    latest = d / "latest"
    facts = read_json(latest / "facts.json")
    scored = read_json(latest / "scored.json")
    private = read_json(latest / "private.json") or {}
    diff = read_json(latest / "diff.json")
    if facts is None or scored is None:
        raise SystemExit("还没有统计结果，先运行：python3 scan.py run")
    checks = scoring.load_checks(CHECKS)
    narrative = render.default_narrative(facts, scored)
    issues = {}
    if narrative_path:
        user_n = read_json(Path(narrative_path))
        if not isinstance(user_n, dict):
            raise SystemExit("narrative.json 读不了，确认是合法的 JSON 对象")
        # 只认模型能看到的 findings.json 里的数字；facts 里成千上万的 token 数会让编造的数字碰巧“对上”
        allowed = render.allowed_numbers(read_json(latest / "findings.json") or {}, facts["totals"], facts["meta"]["window"])
        issues = render.check_narrative(user_n, allowed)
        narrative.update({k: v for k, v in user_n.items() if v})
        if Path(narrative_path).resolve() != (latest / "narrative.json").resolve():
            write_json(latest / "narrative.json", user_n)
        for k, v in issues.items():
            log("! {} 里的数字 {} 在统计结果里找不到".format(k, "、".join(v)))
    html_text = render.render_report(facts, scored, checks, narrative, diff, issues, show_projects, private)
    rp = latest / "report.html"
    rp.write_text(html_text, encoding="utf-8")
    weights = {c["id"]: c.get("weight", 1) for c in checks["checks"]}
    cards = render.write_cards(latest, facts, scored, narrative, private, weights, checks)
    return {"report": str(rp), "cards": cards, "issues": issues}


def cmd_render(args) -> int:
    d = data_dir(args.out)
    narr = args.narrative
    if narr is None and (d / "latest" / "narrative.json").exists():
        narr = str(d / "latest" / "narrative.json")
    res = do_render(d, narr, args.show_projects)
    print(json.dumps({"ok": True, "report": res["report"], "cards": res["cards"],
                      "unverified_numbers": res["issues"]}, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    if sys.version_info < (3, 9):
        print("需要 Python 3.9 或更高版本", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog="scan.py", description="Agent 使用体检（v{}）".format(TOOL_VERSION))
    ap.add_argument("--home", help=argparse.SUPPRESS)  # 测试用：换一个“家目录”
    ap.add_argument("--out", help="输出目录，默认 ~/.agent-usage-report")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect", help="检测本机有哪些 Agent")
    r = sub.add_parser("run", help="统计并生成报告")
    r.add_argument("--days", type=int, default=30, help="统计最近多少天，默认 30")
    r.add_argument("--since", help="从哪天开始统计，如 2026-10-01")
    r.add_argument("--retest", action="store_true", help="复测：从上次体检的时间点开始统计")
    r.add_argument("--agents", help="只统计这些，逗号分隔：claude_code,codex,cursor")
    r.add_argument("--show-projects", action="store_true", help="本机报告里显示项目真名（分享卡永远不显示）")
    g = sub.add_parser("render", help="用模型写的总评重新渲染")
    g.add_argument("--narrative", help="narrative.json 路径")
    g.add_argument("--show-projects", action="store_true")
    args = ap.parse_args(argv)
    for k in ("out", "home"):
        if not hasattr(args, k):
            setattr(args, k, None)
    if args.cmd == "detect":
        return cmd_detect(args)
    if args.cmd == "run":
        return cmd_run(args)
    return cmd_render(args)


if __name__ == "__main__":
    sys.exit(main())
