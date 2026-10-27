"""渲染 HTML 报告和分享卡。模型写的文字（narrative.json）只填进固定位置，数字要能在 facts 里找到。"""
from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path

from redact import card_text_safe

E = html.escape
VERDICT = {
    "good": ("✅", "做对了", "good"),
    "bad": ("⚠️", "用错了", "bad"),
    "unused": ("⭕", "没用上", "unused"),
    "na": ("➖", "数据不足", "na"),
    "info": ("ℹ️", "仅供参考", "info"),
}
RX_KIND = {"command": "命令", "prompt": "提示词", "config": "配置", "action": "操作"}
AGENT_NAMES = {"claude_code": "Claude Code", "codex": "Codex", "cursor": "Cursor", "_global": "所有 Agent"}
LEVEL_TEXT = {"full": "逐条分析", "session": "会话级", "config": "仅配置", "none": "未检测到"}


# ---------- 数字校验 ----------

_NUM = re.compile(r"\d+(?:\.\d+)?")


def allowed_numbers(*objs) -> set:
    nums = set()
    for o in objs:
        for m in _NUM.findall(json.dumps(o, ensure_ascii=False)):
            nums.add(m)
            try:
                f = float(m)
                nums.add(str(int(round(f))))
                nums.add(("%.1f" % f).rstrip("0").rstrip("."))
            except ValueError:
                pass
    nums |= {str(i) for i in range(0, 11)}
    return nums


def unverified_numbers(text: str, allowed: set) -> list:
    bad = []
    for m in _NUM.findall(text or ""):
        if m not in allowed and m.rstrip("0").rstrip(".") not in allowed:
            bad.append(m)
    return bad


def check_narrative(narr: dict, allowed: set) -> dict:
    """返回 {字段路径: [对不上的数字]}。"""
    issues = {}

    def walk(v, path):
        if isinstance(v, str):
            b = unverified_numbers(v, allowed)
            if b:
                issues[path] = b
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, path + "." + str(k))
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, "{}[{}]".format(path, i))

    walk(narr, "narrative")
    return issues


# ---------- 默认文字（没有 narrative 时） ----------

def default_narrative(facts, scored) -> dict:
    c = scored["counts"]
    bads = [x for x in scored["checks"] if x["overall"] == "bad"]
    unused = [x for x in scored["checks"] if x["overall"] == "unused"]
    t = facts["totals"]
    head = "做对 {} 项，用错 {} 项，没用上 {} 项".format(c["good"], c["bad"], c["unused"])
    summary = "统计了 {} 天里的 {} 个会话、{} 条消息。".format(facts["meta"]["window"]["days"], t["sessions"], t["user_messages"])
    if bads:
        summary += "最该先改的是：" + "、".join(x["title"] for x in bads[:3]) + "。"
    return {
        "headline": head,
        "summary": summary,
        "top3": [x["title"] for x in (bads + unused)[:3]],
        "card_quote": "",
        "findings": {},
    }


# ---------- 改进清单 ----------

def pick_actions(scored, checks, facts, limit=5):
    rx_by_id = {c["id"]: c for c in checks["checks"]}
    cands = []
    for r in scored["checks"]:
        if r["overall"] not in ("bad", "unused"):
            continue
        chk = rx_by_id[r["id"]]
        # 选会话最多、且判定不是 good 的那个 Agent 的处方
        agents = sorted(((a, x) for a, x in r["per_agent"].items() if x["verdict"] in ("bad", "unused")),
                        key=lambda kv: -kv[1].get("weight", 0))
        if not agents:
            continue
        aid = agents[0][0]
        rx = (chk.get("rx") or {}).get(aid) or []
        if not rx:
            continue
        sev = (2 if r["overall"] == "bad" else 1) * chk.get("weight", 1) * chk.get("priority", 1)
        cands.append((sev, r, chk, aid, rx))
    cands.sort(key=lambda x: -x[0])
    out = []
    for sev, r, chk, aid, rx in cands[:limit]:
        first = rx[0]
        col = {"command": "now", "prompt": "habit", "config": "setup"}.get(first["kind"], "habit")
        out.append({"id": r["id"], "title": chk["title"], "agent": aid, "rx": rx, "column": col,
                    "retest": chk.get("retest", ""), "verdict": r["overall"]})
    return out


def fix_prompt(actions) -> str:
    lines = ["请按下面的清单帮我改进 Agent 的使用配置。规则：每改一处配置文件，先给我看 diff，等我确认再写入；只是习惯类的建议，整理成一张便签给我就行。", ""]
    for i, a in enumerate(actions, 1):
        lines.append("{}. {}（{}）".format(i, a["title"], AGENT_NAMES.get(a["agent"], a["agent"])))
        for rx in a["rx"]:
            body = rx["text"].split("\n")
            lines.append("   - {}：{}".format(RX_KIND.get(rx["kind"], rx["kind"]), body[0]))
            lines += ["       " + x for x in body[1:]]
    lines.append("")
    lines.append("全部完成后，告诉我改了哪些文件，以及哪些需要我自己养成习惯。")
    return "\n".join(lines)


def _score_color(score):
    if score is None:
        return "var(--na)"
    if score >= 80:
        return "var(--good)"
    if score >= 60:
        return "var(--unused)"
    return "var(--bad)"


def render_report(*args, **kwargs):
    from report_html import render_report as _r
    return _r(*args, **kwargs)


# ---------- 分享卡 ----------

def card_data(facts, scored, narrative, weights=None, checks=None):
    agents = [a["name"] for a in facts["agents"].values() if a["sessions"]]
    c = scored["counts"]
    t = facts["totals"]
    stats = ["{} 个会话 · {} 天".format(t["sessions"], facts["meta"]["window"]["days"]),
             "做对 {} · 用错 {} · 没用上 {}".format(c["good"], c["bad"], c["unused"])]
    w = weights or {}
    bad = sorted([x for x in scored["checks"] if x["overall"] == "bad"], key=lambda x: -w.get(x["id"], 1))
    good = sorted([x for x in scored["checks"] if x["overall"] == "good"], key=lambda x: -w.get(x["id"], 1))
    if good:
        stats.append("强项：" + good[0]["title"])
    if checks:
        acts = pick_actions(scored, checks, facts, limit=1)
        if acts:
            prob = next((c.get("problem") for c in checks["checks"] if c["id"] == acts[0]["id"]), None)
            stats.append("短板：" + (prob or acts[0]["title"]))
    elif bad:
        stats.append("短板：" + bad[0]["title"])
    return {
        "total": scored["total"],
        "grade": scored["grade"],
        "sections": [(v["title"], v["score"]) for v in scored["sections"].values()],
        "agents": agents,
        "stats": stats[:4],
        "quote": (narrative.get("card_quote") or "")[:24],
    }


def _bar(x, y, w, label, score):
    val = 0 if score is None else score
    col = {"var(--good)": "#22c55e", "var(--unused)": "#60a5fa", "var(--bad)": "#fb923c", "var(--na)": "#6b7280"}[_score_color(score)]
    return ('<text x="{x}" y="{y}" class="t2">{lab}</text><text x="{xr}" y="{y}" class="t2" text-anchor="end">{v}</text>'
            '<rect x="{x}" y="{yb}" width="{w}" height="10" rx="5" fill="#2a2f3a"/>'
            '<rect x="{x}" y="{yb}" width="{wv:.0f}" height="10" rx="5" fill="{col}"/>').format(
        x=x, y=y, xr=x + w, lab=E(label), v="—" if score is None else score, yb=y + 10, w=w, wv=w * val / 100.0, col=col)


def render_card(d, width, height) -> str:
    total = "—" if d["total"] is None else str(d["total"])
    style = ('<style>.t1{font:700 44px -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;fill:#f3f4f6}'
             '.t2{font:500 22px -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;fill:#cbd5e1}'
             '.t3{font:400 20px -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;fill:#94a3b8}'
             '.big{font:800 120px -apple-system,"PingFang SC",sans-serif;fill:#fff}'
             '.q{font:600 30px -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;fill:#fde68a}</style>')
    bg = ('<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b1020"/>'
          '<stop offset="1" stop-color="#1e293b"/></linearGradient></defs><rect width="100%" height="100%" fill="url(#g)"/>')
    r = 120
    col = {"var(--good)": "#22c55e", "var(--unused)": "#60a5fa", "var(--bad)": "#fb923c", "var(--na)": "#6b7280"}[_score_color(d["total"])]
    circ = 2 * math.pi * r
    off = circ * (1 - (0 if d["total"] is None else d["total"]) / 100.0)
    if width > height:  # 横版 1200×675
        cx, cy = 220, 330
        body_x, top = 440, 110
    else:  # 竖版 1080×1350
        cx, cy = width / 2.0, 420
        body_x, top = 140, 640
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'.format(w=width, h=height), style, bg]
    title_y = 80 if width > height else 120
    title_x = 60 if width > height else width / 2.0
    anchor = "start" if width > height else "middle"
    parts.append('<text x="{}" y="{}" class="t1" text-anchor="{}">我的 Agent 使用体检</text>'.format(title_x, title_y, anchor))
    parts.append('<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#2a2f3a" stroke-width="22"/>'
                 '<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{col}" stroke-width="22" stroke-linecap="round" '
                 'stroke-dasharray="{c:.1f}" stroke-dashoffset="{o:.1f}" transform="rotate(-90 {cx} {cy})"/>'
                 '<text x="{cx}" y="{ty}" class="big" text-anchor="middle">{t}</text>'
                 '<text x="{cx}" y="{gy}" class="t2" text-anchor="middle">{g}</text>'.format(
                     cx=cx, cy=cy, r=r, col=col, c=circ, o=off, ty=cy + 40, t=E(total), gy=cy + 82,
                     g=E("{} · {}".format(d["grade"]["letter"], d["grade"]["label"]))))
    bw = (width - body_x - 60) if width > height else (width - 2 * body_x)
    y = top + (20 if width > height else 0)
    for label, score in d["sections"]:
        parts.append(_bar(body_x, y, bw, label, score))
        y += 62
    y += 10
    for s in d["stats"]:
        parts.append('<text x="{}" y="{}" class="t2">· {}</text>'.format(body_x, y, E(s)))
        y += 36
    if d["quote"]:
        parts.append('<text x="{}" y="{}" class="q">“{}”</text>'.format(body_x, y + 14, E(d["quote"])))
    foot = "{} · 本地统计，不含项目信息 · agent-usage-report".format(" + ".join(d["agents"]) or "—")
    parts.append('<text x="{}" y="{}" class="t3" text-anchor="{}">{}</text>'.format(title_x, height - 40, anchor, E(foot)))
    parts.append("</svg>")
    return "".join(parts)


def card_text(d) -> str:
    """卡片上唯一可能含私人信息的是模型写的金句；统计行和产品名都来自固定词表。"""
    return d["quote"]


def write_cards(out_dir: Path, facts, scored, narrative, private, weights=None, checks=None) -> dict:
    d = card_data(facts, scored, narrative, weights, checks)
    forbidden = list(((private or {}).get("project_names") or {}).values()) + [(private or {}).get("user", "")]
    notes = []
    if d["quote"] and not card_text_safe(card_text(d), forbidden):
        d["quote"] = ""
        notes.append("金句里疑似有项目名、路径或用户名，已从分享卡上去掉")
    files = {}
    svgs = {}
    for name, (w, h) in {"share-card-x": (1200, 675), "share-card-xhs": (1080, 1350)}.items():
        svg = render_card(d, w, h)
        p = out_dir / (name + ".svg")
        p.write_text(svg, encoding="utf-8")
        files[name] = str(p)
        svgs[name] = (svg, w, h)
    hp = out_dir / "share-card.html"
    hp.write_text(card_page(svgs), encoding="utf-8")
    files["html"] = str(hp)
    return {"ok": True, "files": files, "notes": notes}


CARD_JS = """
function dl(id,w,h,name){var svg=document.getElementById(id).innerHTML;
var img=new Image();img.onload=function(){var c=document.createElement('canvas');c.width=w*2;c.height=h*2;
var x=c.getContext('2d');x.scale(2,2);x.drawImage(img,0,0,w,h);c.toBlob(function(b){var a=document.createElement('a');
a.href=URL.createObjectURL(b);a.download=name;a.click();});};
img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);}
"""


def card_page(svgs) -> str:
    blocks = []
    for name, (svg, w, h) in svgs.items():
        blocks.append('<div class="item"><div id="{n}" class="card" style="aspect-ratio:{w}/{h}">{svg}</div>'
                      '<button type="button" onclick="dl(\'{n}\',{w},{h},\'{n}.png\')">下载 PNG（{w}×{h}）</button></div>'.format(
                          n=name, w=w, h=h, svg=svg))
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>分享卡</title>'
            '<style>body{margin:0;background:#111;color:#aaa;font:14px -apple-system,"PingFang SC",sans-serif;'
            'display:flex;flex-direction:column;align-items:center;gap:28px;padding:24px}'
            '.item{display:flex;flex-direction:column;align-items:center;gap:10px;width:min(100%,900px)}'
            '.card{width:100%}.card svg{width:100%;height:auto;display:block;box-shadow:0 10px 40px rgba(0,0,0,.5)}'
            'button{font-size:15px;padding:8px 16px;border-radius:8px;border:0;background:#fde68a;color:#111;cursor:pointer}</style>'
            '</head><body><p>点按钮下载 PNG（2 倍清晰度）。卡片不含项目名和路径。</p>'
            + "".join(blocks) + "<script>" + CARD_JS + "</script></body></html>")
