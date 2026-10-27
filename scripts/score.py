"""按检查项库给每个 Agent 判定：good / bad / unused / na / info，并算分。

判定逻辑在这里，阈值在 checks/checks.json 的 params 里，处方模板也在 checks.json。
"""
from __future__ import annotations

import json
from pathlib import Path

VERDICT_SCORE = {"good": 1.0, "unused": 0.3, "bad": 0.0}
MIN_SESSIONS_FOR_SCORE = 5
MIN_MESSAGES_FOR_SCORE = 30


def load_checks(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def R(verdict, value, finding, evidence=None, **metrics):
    return {"verdict": verdict, "value": value, "finding": finding, "evidence": evidence or [], "metrics": metrics}


def _sess(b):
    """把一个会话证据写成一句话：项目 B · 10-12 · 76 条消息"""
    parts = [b["project"], (b.get("date") or "")[5:]]
    return " · ".join(x for x in parts if x)


def _na(why):
    return R("na", "—", why)


# ---------- 各检查项 ----------

def A1(a, p):
    m, b = a["messages"], a["behavior"]
    n = a["sessions_full"]
    if n < 3:
        return _na("会话太少，暂不判断")
    long_share = b["long_sessions"] / n
    clear = b["clear"]
    value = "长会话 {} 个 / {}".format(b["long_sessions"], n)
    base = "{} 个会话，单个会话最多 {} 条消息，超过 {} 条的有 {} 个".format(
        n, m["per_session_max"], p["long_session_msgs"], b["long_sessions"])
    ev = ["最长的会话：{}，{} 条消息{}".format(_sess(x), x["messages"], "，跨了 {} 小时".format(int(x["hours"])) if x["hours"] >= 24 else "")
          for x in (a.get("evidence") or {}).get("longest", []) if x["messages"] > p["long_session_msgs"]]
    if clear > 0:
        return R("good", value, base + "，用过 {} 次清空上下文。".format(clear), ev, clear=clear)
    if long_share >= p["long_share_bad"]:
        return R("bad", value, base + "，一次 /clear 都没用过。", ev, clear=0, long_share=round(long_share, 2))
    if m["per_session_p90"] <= p["p90_good"]:
        return R("good", value, base + "，大部分会话都很短，相当于自然地“换任务开新会话”。", ev)
    return R("unused", value, base + "，会话偏长但没用过 /clear。", ev)


def A2(a, p):
    n = a["sessions"]
    if n < 3:
        return _na("会话太少，暂不判断")
    auto = a["behavior"]["compact_auto"]
    per10 = round(auto * 10.0 / n, 1)
    value = "每 10 个会话 {} 次".format(per10)
    text = "{} 个会话里被自动压缩 {} 次，折合每 10 个会话 {} 次".format(n, auto, per10)
    e = a.get("evidence") or {}
    ev = []
    md, mc = e.get("compaction_multi_day_sessions", 0), e.get("compaction_multi_day_count", 0)
    if md and auto:
        ev.append("{} 个跨天挂着用的长会话贡献了其中 {} 次（{}%）——问题主要出在“一个会话用好几天”".format(
            md, mc, round(100.0 * mc / auto)))
    for x in e.get("compaction_top", [])[:3]:
        ev.append("{}：被压缩 {} 次，{} 条消息，前后持续 {} 小时".format(_sess(x), x["compactions"], x["messages"], int(x["hours"])))
    if per10 <= p["per10_good"]:
        return R("good", value, text + "，上下文控制得不错。", per10=per10)
    return R("bad", value, text + "，经常把上下文撑满。", ev, per10=per10)


def A3(a, p):
    b = a["behavior"]
    if b["compact_manual"] > 0:
        return R("good", "{} 次".format(b["compact_manual"]), "主动压缩过 {} 次。".format(b["compact_manual"]))
    if b["compact_auto"] == 0:
        return _na("还没出现上下文被撑满的情况，暂时用不上")
    return R("unused", "0 次", "被自动压缩 {} 次，但从没主动用过 /compact。".format(b["compact_auto"]))


def A4(a, p):
    n = a["sessions_full"]
    if n < 3:
        return _na("会话太少，暂不判断")
    k = a["behavior"]["neg_loop_sessions"]
    share = k / n
    value = "{} 个会话".format(k)
    if share >= p["bad_share"]:
        return R("bad", value, "{} 个会话里有 {} 个出现连续三次以上纠错（“不对”“还是不行”这类开头）。".format(n, k))
    if k == 0:
        return R("good", value, "{} 个会话里，没有一个出现连续三次以上的纠错。".format(n))
    return R("good", value, "{} 个会话里，只有 {} 个出现连续三次以上的纠错。".format(n, k))


def A5(a, p):
    b = a["behavior"]
    calls = b["subagent_calls"] or b["subagent_sessions"]
    if calls > 0:
        return R("good", "{} 次".format(calls), "用过 {} 次子代理（{} 个会话里用到）。".format(calls, b["sessions_with_subagent"]))
    return R("unused", "0 次", "子代理 0 次；平均每个会话读文件 {} 次，调研都在主会话里做。".format(b["reads_per_session"]))


def A6(a, p):
    n = a["behavior"]["btw"]
    if n:
        return R("good", "{} 次".format(n), "用过 {} 次 /btw。".format(n))
    return R("unused", "0 次", "没用过 /btw。")


def B1(a, p):
    b = a["behavior"]
    if b["edit_sessions"] == 0:
        return _na("没有改代码的会话")
    if b["plan_sessions"]:
        return R("good", "{} 个会话".format(b["plan_sessions"]), "{} 个会话用过 Plan 模式。".format(b["plan_sessions"]))
    return R("unused", "0 次", "{} 个改过代码的会话，一次都没进 Plan 模式。".format(b["edit_sessions"]))


def B2(a, p):
    b = a["behavior"]
    if b["edit_sessions"] < 3:
        return _na("改代码的会话太少（只改文档的会话不要求跑测试）")
    pct = round(100.0 * b["verify_sessions"] / b["edit_sessions"])
    value = "{}%".format(pct)
    text = "{} 个改过代码的会话里，{} 个在改完后跑过测试、构建、lint 或浏览器检查（{}%）".format(
        b["edit_sessions"], b["verify_sessions"], pct)
    ev = ["没验证的改代码会话：{}，{} 条消息".format(_sess(x), x["messages"])
          for x in (a.get("evidence") or {}).get("unverified_code_sessions", [])]
    if b.get("doc_only_sessions"):
        ev.append("另有 {} 个会话只改了文档，不要求跑测试，没算进来".format(b["doc_only_sessions"]))
    if pct >= p["good_pct"]:
        return R("good", value, text + "。", ev, pct=pct)
    return R("bad", value, text + "，其余靠你自己验收。", ev, pct=pct)


def B3(a, p):
    m = a["messages"]
    if m["total"] < 20:
        return _na("消息太少")
    value = "中位 {} 字".format(int(m["median_chars"]))
    text = "{} 条消息，长度中位数 {} 字；6 字以内的短消息占 {}%；带文件引用的占 {}%".format(
        m["total"], int(m["median_chars"]), m["short_pct"], m["file_ref_pct"])
    if (m["short_pct"] or 0) >= p["short_pct_bad"] or m["median_chars"] < p["median_chars_bad"]:
        return R("bad", value, text + "，提示词偏短。")
    return R("good", value, text + "。")


def B4(a, p, agent):
    b = a["behavior"]
    n = b["interrupts"]
    tip = "（连按两次 Esc 回退不会留下记录，这里统计不到。）" if agent == "claude_code" else ""
    if n:
        return R("good", "打断 {} 次".format(n), "看到方向不对会及时打断，一共 {} 次。".format(n) + tip)
    return R("unused", "0 次", "从没打断过 Agent。方向不对时尽早按 Esc，比等它做完再返工省事。" + tip)


def B5(a, p):
    b = a["behavior"]
    if b["goal_sessions"]:
        return R("good", "{} 个会话".format(b["goal_sessions"]), "{} 个会话用过 goal。".format(b["goal_sessions"]))
    if b["continue_msgs"] >= p["continue_msgs"]:
        return R("unused", "“继续” {} 次".format(b["continue_msgs"]),
                 "发过 {} 次“继续”之类的消息，但没用过 /goal。".format(b["continue_msgs"]))
    return _na("长任务不多，暂时用不上")


def B6(a, p):
    n = a["behavior"]["ask_user"]
    if n:
        return R("good", "{} 次".format(n), "Agent 主动用 AskUserQuestion 问过你 {} 次。".format(n))
    return R("unused", "0 次", "从没让它采访过你。")


def B7(a, p):
    n = a["behavior"]["review_sessions"]
    if n:
        return R("good", "{} 个会话".format(n), "{} 个会话做过独立审查。".format(n))
    if a["behavior"]["edit_sessions"] == 0:
        return _na("没有改代码的会话")
    return R("unused", "0 次", "改过代码的会话 {} 个，没做过独立审查。".format(a["behavior"]["edit_sessions"]))


def C1(a, p):
    c = a.get("config") or {}
    pr = c.get("project_rules") or {}
    n = pr.get("projects") or 0
    g = c.get("global_rules") or {}
    if n == 0:
        return _na("统计窗口里没有常用项目（至少 2 个会话或 10 条消息）")
    pct = pr.get("coverage_pct") or 0
    value = "{}/{} 个项目".format(pr["covered"], n)
    gtxt = "；全局规则文件{}".format("有" if g else "没有")
    text = "常用的 {} 个项目里，{} 个有规则文件（{}%）{}".format(n, pr["covered"], pct, gtxt)
    ev = ["没有规则文件：{}（{} 个会话、{} 条消息）".format(x["label"], x["sessions"], x["messages"])
          for x in (pr.get("uncovered") or [])[:5]]
    if pct >= p["good_pct"]:
        return R("good", value, text + "。", ev, pct=pct)
    return R("bad", value, text + "。", ev, pct=pct)


def C2(a, p, agent):
    c = a.get("config") or {}
    pr = c.get("project_rules") or {}
    longest = pr.get("max_lines") or 0
    if agent == "codex":
        cap = c.get("project_doc_max_bytes") or 32768
        b = pr.get("max_chain_bytes") or 0
        if not b and not longest:
            return _na("没有规则文件")
        if b > cap:
            return R("bad", "{} KB".format(round(b / 1024, 1)),
                     "最长一条 AGENTS.md 链合计 {} KB，超过上限 {} KB，后面的会被截掉。".format(round(b / 1024, 1), cap // 1024))
        return R("good", "{} KB".format(round(b / 1024, 1)), "最长一条 AGENTS.md 链 {} KB，在 {} KB 上限以内。".format(round(b / 1024, 1), cap // 1024))
    cap = p["cursor_max_lines"] if agent == "cursor" else p["claude_max_lines"]
    if not longest:
        return _na("没有规则文件")
    if longest > cap:
        return R("bad", "{} 行".format(longest), "最长的规则文件 {} 行，超过 {} 行。".format(longest, cap))
    return R("good", "{} 行".format(longest), "最长的规则文件 {} 行，在 {} 行以内。".format(longest, cap))


def C3(a, p):
    c = a.get("config") or {}
    inst = c.get("skills_installed") or 0
    used = c.get("skills_used") or 0
    if inst == 0:
        return R("unused", "0 个", "没有安装任何 Skill。")
    pct = round(100.0 * used / inst)
    value = "用了 {}/{}".format(used, inst)
    dp = c.get("skills_desktop_plugin", 0)
    text = "去重后装了 {} 个 Skill（自己装的 {}、插件带的 {}{}，有的两边都有），统计窗口里用到 {} 个（{}%）".format(
        inst, c.get("skills_personal", 0), c.get("skills_plugin", 0),
        "，其中桌面 App 从账号同步的 {} 个".format(dp) if dp else "", used, pct)
    if inst > p["many"] and pct < p["used_pct_bad"]:
        return R("bad", value, text + "，其余每轮都在占上下文。", pct=pct)
    return R("good", value, text + "。", pct=pct)


def C4(inv):
    d = inv.get("duplicate_count") or 0
    total = inv.get("unique") or 0
    dirs = len(inv.get("per_dir") or {})
    if total == 0:
        return _na("没有找到 Skill")
    return R("info", "{} 个重复".format(d), "{} 个 Skill 目录里共有 {} 个不同的 Skill，其中 {} 个在多个目录里各装了一份。".format(dirs, total, d))


def C5(a, p):
    c = a.get("config") or {}
    conf = c.get("mcp_configured") or []
    unused = c.get("mcp_unused") or []
    if not conf:
        return _na("没有配置 MCP")
    if a["sessions"] == 0:
        return R("info", "{} 个".format(len(conf)), "配置了 {} 个 MCP 服务器（该产品的使用情况暂不统计）。".format(len(conf)))
    value = "闲置 {}/{}".format(len(unused), len(conf))
    if unused:
        return R("bad", value, "配置了 {} 个 MCP 服务器，{} 个在统计窗口里一次都没用过。".format(len(conf), len(unused)))
    return R("good", value, "配置的 {} 个 MCP 服务器都用到了。".format(len(conf)))


def C6(a, p, agent):
    modes = a.get("modes") or {}
    total = sum(modes.values())
    if not total:
        return _na("没有权限模式记录")
    if agent == "codex":
        wide = sum(v for k, v in modes.items() if k.endswith("danger-full-access") and k.startswith("never"))
        label = "不审批且不设沙箱（never + danger-full-access）"
    else:
        wide = modes.get("bypassPermissions", 0)
        label = "跳过全部权限检查（bypassPermissions）"
    pct = round(100.0 * wide / total)
    top = sorted(modes.items(), key=lambda x: -x[1])[0][0]
    ev = []
    if agent == "codex" and not ((a.get("config") or {}).get("permissions") or {}).get("approval_policy"):
        ev.append("config.toml 里没有设置权限，这些轮次来自 App 输入框旁的权限菜单（选了 Full access）")
    if pct >= p["bad_pct"]:
        return R("bad", "{}%".format(pct), "{}% 的轮次处于{}。".format(pct, label), ev, pct=pct)
    return R("good", "{}%".format(pct), "最常用的权限模式是 {}，完全放开的轮次只占 {}%。".format(top, pct), pct=pct)


def C7(a, p):
    n = (a.get("config") or {}).get("hooks") or 0
    if n:
        return R("good", "{} 个".format(n), "配置了 {} 个 hook。".format(n))
    return R("unused", "0 个", "没有配置任何 hook。")


def C8(a, p):
    c = a.get("config") or {}
    n = c.get("secrets_found") or 0
    if not (c.get("project_rules") or {}).get("max_lines") and not c.get("global_rules"):
        return _na("没有规则文件")
    if n:
        return R("bad", "{} 处".format(n), "规则文件里有 {} 处疑似密钥或 token（报告里不显示内容）。".format(n))
    return R("good", "0 处", "规则文件里没发现疑似密钥。")


def D1(a, p, agent):
    if agent == "codex":
        eff = a.get("efforts") or {}
        total = sum(eff.values())
        if not total:
            return _na("没有推理强度记录")
        hi = sum(v for k, v in eff.items() if k in ("high", "xhigh", "max", "ultra"))
        pct = round(100.0 * hi / total)
        dist = "、".join("{} {}%".format(k, round(100.0 * v / total)) for k, v in sorted(eff.items(), key=lambda x: -x[1]))
        if pct >= p["top_pct"]:
            return R("unused", "高强度 {}%".format(pct), "推理强度分布：{}；high 及以上合计 {}%，几乎都开高档。".format(dist, pct), pct=pct)
        return R("good", "高强度 {}%".format(pct), "推理强度分布：{}；high 及以上合计 {}%。".format(dist, pct), pct=pct)
    tiers = a.get("model_tiers") or {}
    total = sum(tiers.values())
    if not total:
        return _na("没有模型记录")
    top = round(100.0 * tiers.get("top", 0) / total)
    dist = "、".join("{} {}%".format(k, round(100.0 * v / total)) for k, v in list((a.get("models") or {}).items())[:3])
    if top >= p["top_pct"]:
        return R("unused", "最贵档 {}%".format(top), "模型分布：{}，大部分活都交给最贵的一档。".format(dist), pct=top)
    return R("good", "最贵档 {}%".format(top), "模型分布：{}。".format(dist), pct=top)


def D2(a, p):
    hit = a.get("cache_hit_pct")
    if hit is None:
        return _na("没有 token 记录")
    if hit >= p["good_pct"]:
        return R("good", "{}%".format(hit), "缓存命中率 {}%。".format(hit), pct=hit)
    return R("bad", "{}%".format(hit), "缓存命中率只有 {}%。".format(hit), pct=hit)


def D3(a, p):
    b = a["behavior"]
    if b["max_parallel"] > 1 or b["worktree_sessions"]:
        return R("good", "最多 {} 个同时".format(b["max_parallel"]),
                 "最多 {} 个会话在同一个半小时里同时干活，这样的时间片有 {} 个；用到 worktree 的会话 {} 个。".format(
                     b["max_parallel"], b.get("parallel_slots", 0), b["worktree_sessions"]))
    return R("unused", "1 个", "会话都是一个接一个，没并行过。")


EVAL = {
    "A1": A1, "A2": A2, "A3": A3, "A4": A4, "A5": A5, "A6": A6,
    "B1": B1, "B2": B2, "B3": B3, "B4": B4, "B5": B5, "B6": B6, "B7": B7,
    "C1": C1, "C2": C2, "C3": C3, "C5": C5, "C6": C6, "C7": C7, "C8": C8,
    "D1": D1, "D2": D2, "D3": D3,
}
NEEDS_AGENT = {"B4", "C2", "C6", "D1"}
CONFIG_ONLY_OK = {"C2", "C5", "C7", "C8"}


def score(facts: dict, checks: dict) -> dict:
    results = []
    sections = {k: {"num": 0.0, "den": 0.0} for k in checks["sections"]}
    for chk in checks["checks"]:
        cid = chk["id"]
        p = chk.get("params") or {}
        per_agent = {}
        if cid == "C4":
            per_agent["_global"] = C4(facts.get("skills_inventory") or {})
        else:
            fn = EVAL[cid]
            for aid, a in facts["agents"].items():
                if aid not in chk["applies_to"]:
                    continue
                if a["sessions"] == 0 and not (a["level"] == "config" and cid in CONFIG_ONLY_OK and a.get("config")):
                    continue
                r = fn(a, p, aid) if cid in NEEDS_AGENT else fn(a, p)
                if a["sessions"] == 0 and r["verdict"] in VERDICT_SCORE:
                    r["note"] = "仅配置体检，不计分"
                    r["scored"] = False
                else:
                    r["scored"] = r["verdict"] in VERDICT_SCORE
                r["weight"] = a["sessions"]
                per_agent[aid] = r
        if not per_agent:
            continue
        # 合并：按会话数加权
        num = den = 0.0
        for r in per_agent.values():
            if r.get("scored"):
                w = max(1, r["weight"])
                num += VERDICT_SCORE[r["verdict"]] * w
                den += w
        check_score = (num / den) if den else None
        if check_score is not None and chk.get("weight", 1) > 0:
            sections[chk["section"]]["num"] += check_score * chk["weight"]
            sections[chk["section"]]["den"] += chk["weight"]
        results.append({
            "id": cid,
            "section": chk["section"],
            "title": chk["title"],
            "score": None if check_score is None else round(check_score * 100),
            "overall": _overall(per_agent),
            "per_agent": per_agent,
        })

    sec_out = {}
    total_num = total_den = 0.0
    for k, meta in checks["sections"].items():
        s = sections[k]
        val = round(100 * s["num"] / s["den"]) if s["den"] else None
        sec_out[k] = {"title": meta["title"], "score": val, "weight": meta["weight"]}
        if val is not None:
            total_num += val * meta["weight"]
            total_den += meta["weight"]
    t = facts["totals"]
    enough = t["sessions"] >= MIN_SESSIONS_FOR_SCORE and t["user_messages"] >= MIN_MESSAGES_FOR_SCORE
    total = round(total_num / total_den) if (total_den and enough) else None
    return {
        "total": total,
        "grade": grade(total),
        "enough_data": enough,
        "sections": sec_out,
        "checks": results,
        "counts": _counts(results),
    }


def _overall(per_agent: dict) -> str:
    vs = [r["verdict"] for r in per_agent.values()]
    scored = [r["verdict"] for r in per_agent.values() if r.get("scored")]
    pool = scored or vs
    for v in ("bad", "unused", "good", "info", "na"):
        if v in pool:
            return v
    return "na"


def _counts(results):
    c = {"good": 0, "bad": 0, "unused": 0, "na": 0, "info": 0}
    for r in results:
        c[r["overall"]] = c.get(r["overall"], 0) + 1
    return c


def grade(total):
    if total is None:
        return {"letter": "—", "label": "样本不足"}
    if total >= 85:
        return {"letter": "A", "label": "老司机"}
    if total >= 70:
        return {"letter": "B", "label": "上手了"}
    if total >= 55:
        return {"letter": "C", "label": "还有不少潜力"}
    return {"letter": "D", "label": "刚起步"}


def diff(prev: dict, cur: dict) -> dict:
    """对比两次体检：总分、分区、每项检查的变化。prev/cur 是 history 里存的 summary。"""
    out = {"prev_date": prev.get("generated_at"), "total": None, "sections": {}, "improved": [], "regressed": []}
    if prev.get("total") is not None and cur.get("total") is not None:
        out["total"] = {"from": prev["total"], "to": cur["total"], "delta": cur["total"] - prev["total"]}
    for k, v in (cur.get("sections") or {}).items():
        pv = (prev.get("sections") or {}).get(k)
        if pv is not None and v is not None:
            out["sections"][k] = {"from": pv, "to": v, "delta": v - pv}
    order = {"bad": 0, "unused": 1, "good": 2}
    pc = prev.get("checks") or {}
    for cid, v in (cur.get("checks") or {}).items():
        pv = pc.get(cid)
        if pv in order and v in order and pv != v:
            (out["improved"] if order[v] > order[pv] else out["regressed"]).append({"id": cid, "from": pv, "to": v})
    return out


def summary_for_history(facts: dict, scored: dict) -> dict:
    return {
        "generated_at": facts["meta"]["generated_at"],
        "window": facts["meta"]["window"],
        "total": scored["total"],
        "sections": {k: v["score"] for k, v in scored["sections"].items()},
        "checks": {c["id"]: c["overall"] for c in scored["checks"]},
        "check_values": {c["id"]: {a: r["value"] for a, r in c["per_agent"].items()} for c in scored["checks"]},
    }
