"""体检报告 HTML。单文件、离线可开、不引用任何外部资源。

配色来自 dataviz 默认色板：Agent 身份色固定为第 1、2、3 槽（蓝 / 橙 / 青），
状态色用保留的 good / warning / serious，并且永远配图标和文字。
"""
from __future__ import annotations

import html
import math

E = html.escape

VERDICT = {
    "good": ("✓", "做对了"),
    "bad": ("!", "用错了"),
    "unused": ("○", "没用上"),
    "na": ("–", "数据不足"),
    "info": ("i", "仅供参考"),
}
RX_KIND = {"command": "命令", "prompt": "提示词", "config": "配置", "action": "操作"}
AGENT_NAMES = {"claude_code": "Claude Code", "codex": "Codex", "cursor": "Cursor", "_global": "全局"}
AGENT_SLOT = {"claude_code": 1, "codex": 2, "cursor": 3, "_global": 0}
LEVEL_TEXT = {"full": "逐条分析", "session": "会话级", "config": "仅配置", "none": "未检测到"}
GRADE_NOTE = "满分不代表会用，只代表和官方建议对得上"


# ---------------------------------------------------------------- 样式

CSS = r"""
:root{color-scheme:light;
--page:#f9f9f7;--surface:#fcfcfb;--surface-2:#f3f2ee;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--shadow:0 1px 2px rgba(11,11,11,.04),0 8px 24px rgba(11,11,11,.05);
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;
--good:#0ca30c;--warn:#fab219;--bad:#ec835a;--crit:#d03b3b;--na:#b5b3ac;--info:#898781;
--good-bg:rgba(12,163,12,.10);--warn-bg:rgba(250,178,25,.16);--bad-bg:rgba(236,131,90,.16);--na-bg:rgba(137,135,129,.12);
--accent:#2a78d6;--code:#f1f0ec;--hero-a:#eef4fd;--hero-b:#fdf1ec}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;
--page:#0d0d0d;--surface:#1a1a19;--surface-2:#232321;--ink:#f0efec;--ink-2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25);
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--na:#5c5b57;
--good-bg:rgba(12,163,12,.16);--warn-bg:rgba(250,178,25,.14);--bad-bg:rgba(236,131,90,.16);--na-bg:rgba(137,135,129,.14);
--accent:#3987e5;--code:#232321;--hero-a:#15202e;--hero-b:#2a1b14}}
:root[data-theme="dark"]{color-scheme:dark;
--page:#0d0d0d;--surface:#1a1a19;--surface-2:#232321;--ink:#f0efec;--ink-2:#c3c2b7;--muted:#898781;
--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25);
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--na:#5c5b57;
--good-bg:rgba(12,163,12,.16);--warn-bg:rgba(250,178,25,.14);--bad-bg:rgba(236,131,90,.16);--na-bg:rgba(137,135,129,.14);
--accent:#3987e5;--code:#232321;--hero-a:#15202e;--hero-b:#2a1b14}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:64px}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.7 system-ui,-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:1120px;margin:0 auto;padding:0 24px 96px}
.num{font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}.ink2{color:var(--ink-2)}.small{font-size:13px}
/* 顶栏 */
.top{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--page) 86%,transparent);backdrop-filter:saturate(1.4) blur(10px);border-bottom:1px solid var(--border)}
.top .wrap{display:flex;align-items:center;gap:20px;height:56px;padding-bottom:0}
.brand{font-weight:700;letter-spacing:.2px;white-space:nowrap}.brand span{color:var(--muted);font-weight:500;margin-left:6px}
.nav{display:flex;gap:4px;overflow-x:auto;flex:1;scrollbar-width:none}.nav a{text-decoration:none;color:var(--ink-2);font-size:14px;padding:6px 10px;border-radius:8px;white-space:nowrap}
.nav a:hover{background:var(--surface-2);color:var(--ink)}
.theme{border:1px solid var(--border);background:var(--surface);color:var(--ink-2);border-radius:8px;height:32px;padding:0 10px;cursor:pointer;font-size:13px}
/* 区块 */
section{margin-top:44px}
.sec-h{display:flex;align-items:baseline;gap:12px;margin:0 0 14px}
.sec-h h2{font-size:22px;margin:0;letter-spacing:.2px}.sec-h p{margin:0;color:var(--muted);font-size:14px}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:18px;box-shadow:var(--shadow)}
/* 总评 */
.hero{margin-top:28px;padding:28px;display:grid;grid-template-columns:220px 1fr 300px;gap:32px;align-items:center;
background:linear-gradient(120deg,var(--hero-a),var(--surface) 45%,var(--hero-b))}
.hero h1{font-size:30px;line-height:1.3;margin:0 0 10px;letter-spacing:.3px}
.hero .lead{font-size:15.5px;color:var(--ink-2);margin:0}
.meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);background:var(--surface);border-radius:999px;padding:3px 10px;font-size:12.5px;color:var(--ink-2)}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none;box-shadow:0 0 0 2px var(--surface)}
.d1{background:var(--s1)}.d2{background:var(--s2)}.d3{background:var(--s3)}.d0{background:var(--muted)}
.score{text-align:center}.score .grade{margin-top:6px;font-weight:600}.score .note{font-size:12px;color:var(--muted);margin-top:4px}
.delta-pill{display:inline-block;margin-top:8px;font-size:12.5px;font-weight:600;border-radius:999px;padding:2px 10px;background:var(--good-bg)}
.delta-pill.down{background:var(--bad-bg)}
.meters{display:flex;flex-direction:column;gap:14px}
.meter .row{display:flex;justify-content:space-between;font-size:14px}.meter .row b{font-variant-numeric:tabular-nums}
.meter .track{height:8px;border-radius:4px;background:var(--surface-2);margin-top:6px;overflow:hidden}
.meter .fill{height:100%;border-radius:4px}
.vbar{display:flex;gap:2px;height:10px;border-radius:5px;overflow:hidden;margin-top:18px}
.vbar span{display:block;height:100%}
.vlegend{display:flex;flex-wrap:wrap;gap:14px;margin-top:8px;font-size:13px;color:var(--ink-2)}
/* 状态 */
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;border-radius:999px;padding:2px 10px 2px 4px;color:var(--ink);white-space:nowrap}
.pill i{font-style:normal;width:18px;height:18px;border-radius:50%;display:inline-grid;place-items:center;font-size:11px;font-weight:800;color:#fff}
.v-good{background:var(--good-bg)}.v-good i{background:var(--good)}
.v-bad{background:var(--bad-bg)}.v-bad i{background:var(--bad)}
.v-unused{background:var(--warn-bg)}.v-unused i{background:var(--warn);color:#0b0b0b}
.v-na{background:var(--na-bg)}.v-na i{background:var(--na)}
.v-info{background:var(--na-bg)}.v-info i{background:var(--info)}
.sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
/* 本周就改 */
.todo3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.todo3 .item{padding:18px 18px 16px;display:flex;gap:14px}
.todo3 .n{flex:none;width:30px;height:30px;border-radius:50%;background:var(--ink);color:var(--surface);display:grid;place-items:center;font-weight:700}
/* 体检单 */
.matrix{width:100%;border-collapse:separate;border-spacing:0;font-size:14px}
.matrix th,.matrix td{padding:10px 14px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:middle}
.matrix thead th{font-size:12.5px;color:var(--muted);font-weight:600;background:var(--surface);position:sticky;top:56px;z-index:2}
.matrix tr.grp td{background:var(--surface-2);font-weight:700;font-size:13px;color:var(--ink-2);padding:8px 14px}
.matrix tr.grp td b{color:var(--ink);font-variant-numeric:tabular-nums}
.matrix td.t a{text-decoration:none;font-weight:600}.matrix td.t a:hover{text-decoration:underline}
.matrix td.t .id{color:var(--muted);font-weight:600;margin-right:8px;font-variant-numeric:tabular-nums}
.cell{display:inline-flex;align-items:center;gap:8px}.cell .pill{padding-right:4px}.cell .val{font-variant-numeric:tabular-nums;color:var(--ink-2)}
.matrix tbody tr:not(.grp):hover td{background:var(--surface-2)}
.matrix-wrap{overflow-x:auto;border-radius:18px}
/* 图表 */
.charts{display:grid;grid-template-columns:1.6fr 1fr;gap:14px}
.chart{padding:18px 18px 10px}.chart h3{margin:0;font-size:15px}.chart .sub{font-size:12.5px;color:var(--muted);margin:2px 0 8px}
.legend{display:flex;gap:16px;font-size:12.5px;color:var(--ink-2);margin:4px 0 6px}
svg.viz{width:100%;height:auto;display:block;overflow:visible}
svg.viz text{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
svg.viz .gl{stroke:var(--grid);stroke-width:1}svg.viz .base{stroke:var(--axis);stroke-width:1}
svg.viz .hit{fill:transparent}svg.viz .hit:hover{fill:var(--surface-2);opacity:.6}
.f1{fill:var(--s1)}.f2{fill:var(--s2)}.f3{fill:var(--s3)}
.tableview{margin-top:6px}.tableview summary{font-size:12.5px;color:var(--muted);cursor:pointer}
.tableview table{font-size:12.5px;margin-top:6px;border-collapse:collapse;width:100%}.tableview td,.tableview th{border-bottom:1px solid var(--grid);padding:3px 6px;text-align:right}
.tableview td:first-child,.tableview th:first-child{text-align:left}
#tip{position:fixed;z-index:50;pointer-events:none;background:var(--ink);color:var(--surface);font-size:12.5px;line-height:1.5;padding:6px 10px;border-radius:8px;opacity:0;transition:opacity .08s;white-space:pre;box-shadow:var(--shadow)}
/* 功能雷达 */
.radar{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-top:14px}
.feat{padding:12px 14px;border-radius:14px;border:1px solid var(--border);background:var(--surface)}
.feat .name{font-weight:600;font-size:14px}.feat .vals{margin-top:6px;display:flex;flex-direction:column;gap:2px;font-size:13px;color:var(--ink-2)}
.feat .vals b{color:var(--ink);font-variant-numeric:tabular-nums}
.feat.zero{background:var(--surface-2);border-style:dashed}.feat.zero .name::after{content:"没用过";margin-left:8px;font-size:11.5px;font-weight:600;color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:0 6px}
/* 诊断卡 */
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.card{padding:20px;position:relative;overflow:hidden}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--na)}
.card.c-bad::before{background:var(--bad)}.card.c-unused::before{background:var(--warn)}.card.c-good::before{background:var(--good)}
.card header{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.card h3{margin:0;font-size:17px}.card h3 .id{color:var(--muted);margin-right:6px;font-variant-numeric:tabular-nums}
.card .tag{margin-left:auto;font-size:12px;color:var(--muted)}
.ag{margin-top:14px;padding-top:14px;border-top:1px solid var(--grid)}
.ag .who{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink-2)}
.ag .big{font-size:22px;font-weight:700;margin:2px 0 2px;font-variant-numeric:tabular-nums}
.ag p{margin:0}
.ev{margin:8px 0 0;padding:0;list-style:none;font-size:13.5px;color:var(--ink-2)}
.ev li{padding-left:16px;position:relative;margin-top:3px}.ev li::before{content:"";position:absolute;left:3px;top:.72em;width:5px;height:5px;border-radius:50%;background:var(--axis)}
.basis{margin-top:14px;font-size:12.5px;color:var(--muted)}.basis a{color:var(--ink-2);text-underline-offset:3px}
details.rx{margin-top:12px;border:1px solid var(--border);border-radius:12px;background:var(--surface-2);padding:2px 12px}
details.rx>summary{cursor:pointer;font-weight:600;font-size:14px;padding:8px 0;list-style:none}
details.rx>summary::-webkit-details-marker{display:none}details.rx>summary::before{content:"▸ ";color:var(--muted)}details.rx[open]>summary::before{content:"▾ "}
.code{position:relative;margin:6px 0 10px}.code .k{font-size:11.5px;color:var(--muted);letter-spacing:.5px}
pre{margin:4px 0 0;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 70px 10px 12px;white-space:pre-wrap;word-break:break-word;font:12.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink)}
.copy{position:absolute;right:8px;top:24px;font-size:12px;border:1px solid var(--border);background:var(--surface-2);color:var(--ink-2);border-radius:7px;padding:2px 9px;cursor:pointer}
.copy:hover{color:var(--ink)}
.retest{font-size:12.5px;color:var(--muted);margin:0 0 8px}
.unverified{background:var(--bad-bg);border-bottom:2px dotted var(--bad)}
/* 做对了的 */
.goodlist{padding:6px 0}.goodlist .row{display:grid;grid-template-columns:220px 1fr;gap:16px;padding:12px 20px;border-top:1px solid var(--grid)}
.goodlist .row:first-child{border-top:0}.goodlist .row b{font-size:14.5px}.goodlist .row .id{color:var(--muted);margin-right:6px}
.goodlist .row .txt{font-size:13.5px;color:var(--ink-2)}
/* 表格 */
table.plain{width:100%;border-collapse:collapse;font-size:14px}
table.plain th,table.plain td{padding:10px 16px;border-bottom:1px solid var(--grid);text-align:left}
table.plain thead th{font-size:12.5px;color:var(--muted);font-weight:600}
table.plain tbody th{font-weight:500;color:var(--ink-2);width:180px}
table.plain td{font-variant-numeric:tabular-nums}
table.plain tr:last-child td,table.plain tr:last-child th{border-bottom:0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
/* 改进清单 */
.todo{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.todo .col{padding:18px}.todo h3{margin:0 0 4px;font-size:15px}.todo .hint{font-size:12.5px;color:var(--muted);margin-bottom:6px}
.task{padding:16px 18px}
.task label{display:flex;gap:10px;align-items:flex-start;cursor:pointer;font-weight:600}
.task input{margin-top:5px;width:16px;height:16px;accent-color:var(--good)}
.task.done label span{text-decoration:line-through;color:var(--muted)}
.warn{background:var(--bad-bg);border-radius:12px;padding:10px 14px;margin-top:14px;font-size:14px}
footer{margin-top:56px;font-size:13px;color:var(--muted)}footer ul{padding-left:18px}
@media (max-width:960px){.hero{grid-template-columns:1fr;text-align:left}.score{text-align:left}.charts,.cards,.todo,.todo3,.grid2{grid-template-columns:1fr}
.goodlist .row{grid-template-columns:1fr}}
@media (max-width:600px){.wrap{padding-left:16px;padding-right:16px}.brand span{display:none}.hero{padding:20px}.hero h1{font-size:24px}}
@media print{.top,.copy,.theme{display:none}details{open:true}body{background:#fff}.panel{box-shadow:none}}
"""

JS = r"""
(function(){
var root=document.documentElement,btn=document.getElementById('theme');
var saved=localStorage.getItem('aur-theme');if(saved)root.setAttribute('data-theme',saved);
function label(){var d=root.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');btn.textContent=d==='dark'?'☀︎ 浅色':'☾ 深色';}
if(btn){label();btn.onclick=function(){var d=root.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
var n=d==='dark'?'light':'dark';root.setAttribute('data-theme',n);localStorage.setItem('aur-theme',n);label();};}
document.querySelectorAll('.copy').forEach(function(b){b.addEventListener('click',function(){
var t=b.parentElement.querySelector('pre').textContent;navigator.clipboard.writeText(t).then(function(){b.textContent='已复制';setTimeout(function(){b.textContent='复制'},1400)})})});
var tip=document.getElementById('tip');
document.addEventListener('pointermove',function(e){var t=e.target.closest&&e.target.closest('[data-tip]');
if(!t){tip.style.opacity=0;return;}tip.textContent=t.getAttribute('data-tip');tip.style.opacity=1;
var x=e.clientX+14,y=e.clientY+14,w=tip.offsetWidth,h=tip.offsetHeight;
if(x+w>innerWidth-8)x=e.clientX-w-14;if(y+h>innerHeight-8)y=e.clientY-h-14;tip.style.left=x+'px';tip.style.top=y+'px';});
document.querySelectorAll('.task input').forEach(function(c){var k='aur-done-'+c.dataset.key;
if(localStorage.getItem(k)){c.checked=true;c.closest('.task').classList.add('done');}
c.addEventListener('change',function(){c.closest('.task').classList.toggle('done',c.checked);
if(c.checked)localStorage.setItem(k,'1');else localStorage.removeItem(k);});});
window.addEventListener('scroll',function(){tip.style.opacity=0},{passive:true});
window.addEventListener('beforeprint',function(){document.querySelectorAll('details').forEach(function(d){d.open=true})});
})();
"""


# ---------------------------------------------------------------- 小件

def pill(v, text=None):
    icon, label = VERDICT.get(v, VERDICT["na"])
    return '<span class="pill v-{}"><i aria-hidden="true">{}</i>{}</span>'.format(v, icon, E(text or label))


def dot(aid):
    return '<span class="dot d{}"></span>'.format(AGENT_SLOT.get(aid, 0))


def score_color(score):
    if score is None:
        return "var(--na)"
    if score >= 80:
        return "var(--good)"
    if score >= 60:
        return "var(--warn)"
    return "var(--bad)"


def ring(score, size=180, stroke=14):
    r = (size - stroke) / 2.0
    c = 2 * math.pi * r
    val = 0 if score is None else max(0, min(100, score))
    return (
        '<svg viewBox="0 0 {s} {s}" width="{s}" height="{s}" role="img" aria-label="总分 {t}">'
        '<circle cx="{h}" cy="{h}" r="{r}" fill="none" stroke="var(--surface-2)" stroke-width="{w}"/>'
        '<circle cx="{h}" cy="{h}" r="{r}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linecap="round" '
        'stroke-dasharray="{c:.1f}" stroke-dashoffset="{o:.1f}" transform="rotate(-90 {h} {h})"/>'
        '<text x="{h}" y="{ty}" text-anchor="middle" style="font:800 {fs}px system-ui,-apple-system,sans-serif;fill:var(--ink)">{t}</text>'
        '<text x="{h}" y="{sy}" text-anchor="middle" style="font:500 13px system-ui,-apple-system,sans-serif;fill:var(--muted)">总分 / 100</text></svg>'
    ).format(s=size, h=size / 2.0, r=r, w=stroke, col=score_color(score), c=c, o=c * (1 - val / 100.0),
             t="—" if score is None else score, ty=size / 2.0 + size * 0.1, fs=int(size * 0.3), sy=size / 2.0 + size * 0.24)


def code_block(rx):
    note = '<div class="small muted">{}</div>'.format(E(rx["note"])) if rx.get("note") else ""
    return ('<div class="code"><span class="k">{}</span><button class="copy" type="button">复制</button>'
            '<pre>{}</pre>{}</div>').format(RX_KIND.get(rx["kind"], rx["kind"]), E(rx["text"]), note)


def text_or_flag(s, key, issues):
    if key in issues:
        return '<span class="unverified" title="这句里的数字 {} 在统计结果里找不到，请以卡片上的数值为准">{}</span>'.format(
            E("、".join(issues[key])), E(s))
    return E(s)


def nice_max(v):
    if v <= 0:
        return 1
    exp = 10 ** int(math.floor(math.log10(v)))
    for m in (1, 2, 2.5, 5, 10):
        if m * exp >= v:
            return m * exp
    return 10 * exp


def stacked_columns(series, labels, tips_prefix, every=7, width=720, height=210):
    """series: [(agent_id, name, values)]，按 Agent 堆叠的柱状图。"""
    left, right, top, bottom = 34, 6, 10, 24
    pw, ph = width - left - right, height - top - bottom
    n = len(labels)
    totals = [sum(s[2][i] for s in series) for i in range(n)]
    ymax = nice_max(max(totals) if totals else 0)
    slot = pw / float(max(n, 1))
    bw = min(24.0, slot * 0.64)
    out = ['<svg class="viz" viewBox="0 0 {} {}" role="img">'.format(width, height)]
    for k in range(5):
        v = ymax * k / 4.0
        y = top + ph - ph * v / ymax
        cls = "base" if k == 0 else "gl"
        out.append('<line class="{}" x1="{}" x2="{}" y1="{:.1f}" y2="{:.1f}"/>'.format(cls, left, width - right, y, y))
        lab = int(v) if v == int(v) else round(v, 1)
        out.append('<text x="{}" y="{:.1f}" text-anchor="end" dy="3.5">{}</text>'.format(left - 6, y, lab))
    for i in range(n):
        x = left + slot * i + (slot - bw) / 2.0
        base = top + ph
        segs = [(s[0], s[2][i]) for s in series if s[2][i] > 0]
        for j, (aid, v) in enumerate(segs):
            h = ph * v / ymax
            y = base - h
            gap = 2 if j > 0 else 0
            hh = max(0.0, h - gap)
            if j == len(segs) - 1:
                r = min(4.0, bw / 2.0, hh)
                d = "M{x:.1f},{b:.1f}V{yr:.1f}Q{x:.1f},{y:.1f} {xr:.1f},{y:.1f}H{xe:.1f}Q{x2:.1f},{y:.1f} {x2:.1f},{yr:.1f}V{b:.1f}Z".format(
                    x=x, b=base - gap, y=y, yr=y + r, xr=x + r, xe=x + bw - r, x2=x + bw)
                out.append('<path class="f{}" d="{}"/>'.format(AGENT_SLOT.get(aid, 0), d))
            else:
                out.append('<rect class="f{}" x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}"/>'.format(
                    AGENT_SLOT.get(aid, 0), x, y, bw, hh))
            base = y
        tip = "{}{}\n".format(tips_prefix, labels[i]) + "\n".join(
            "{}：{} 条".format(s[1], s[2][i]) for s in series) + ("\n合计：{} 条".format(totals[i]) if len(series) > 1 else "")
        out.append('<rect class="hit" x="{:.1f}" y="{}" width="{:.1f}" height="{}" rx="4" data-tip="{}"/>'.format(
            left + slot * i, top, slot, ph, E(tip)))
        if i % every == 0 or i == n - 1:
            out.append('<text x="{:.1f}" y="{}" text-anchor="middle">{}</text>'.format(left + slot * i + slot / 2.0, height - 6, E(labels[i])))
    out.append("</svg>")
    # 数据表
    rows = "".join("<tr><td>{}</td>{}</tr>".format(E(labels[i]), "".join("<td>{}</td>".format(s[2][i]) for s in series))
                   for i in range(n))
    head = "".join("<th>{}</th>".format(E(s[1])) for s in series)
    table = '<details class="tableview"><summary>查看数据表</summary><table><tr><th></th>{}</tr>{}</table></details>'.format(head, rows)
    return "".join(out) + table


# ---------------------------------------------------------------- 主体

def render_report(facts, scored, checks, narrative, diff, issues, show_projects=False, private=None) -> str:
    from render import fix_prompt, pick_actions

    meta = facts["meta"]
    w = meta["window"]
    agents = facts["agents"]
    active = [a for a in agents.values() if a["sessions"]]
    chk_meta = {c["id"]: c for c in checks["checks"]}
    sections = checks["sections"]
    o = []
    o.append('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>Agent 使用体检报告</title><style>{}</style></head><body>'.format(CSS))
    # 顶栏
    o.append('<div class="top"><div class="wrap"><div class="brand">Agent 体检<span>{}</span></div><nav class="nav">'
             '<a href="#overview">总评</a><a href="#sheet">体检单</a><a href="#profile">使用画像</a>'
             '<a href="#detail">详细诊断</a><a href="#config">配置</a><a href="#todo">改进清单</a><a href="#appendix">附录</a>'
             '</nav><button id="theme" class="theme" type="button">深色</button></div></div>'.format(E(w["until"])))
    o.append('<div class="wrap">')

    # ---------- 总评
    g = scored["grade"]
    delta_html = ""
    if diff and diff.get("total"):
        d = diff["total"]
        delta_html = '<div class="delta-pill{}">较上次 {:+d} 分</div>'.format(" down" if d["delta"] < 0 else "", d["delta"])
    meters = "".join(
        '<div class="meter"><div class="row"><span>{}</span><b>{}</b></div><div class="track"><div class="fill" style="width:{}%;background:{}"></div></div></div>'.format(
            E(v["title"]), "—" if v["score"] is None else v["score"], v["score"] or 0, score_color(v["score"]))
        for v in scored["sections"].values())
    c = scored["counts"]
    total_checks = sum(c.get(k, 0) for k in ("good", "bad", "unused", "na"))
    vbar = "".join('<span style="width:{:.2f}%;background:var(--{})" title="{} {}"></span>'.format(
        100.0 * c.get(k, 0) / max(total_checks, 1), var, VERDICT[k][1], c.get(k, 0))
        for k, var in (("good", "good"), ("unused", "warn"), ("bad", "bad"), ("na", "na")) if c.get(k, 0))
    vleg = "".join('<span><span class="sw" style="background:var(--{})"></span>{} <b class="num">{}</b></span>'.format(var, VERDICT[k][1], c.get(k, 0))
                   for k, var in (("good", "good"), ("unused", "warn"), ("bad", "bad"), ("na", "na")))
    chips = ['<span class="chip">统计 {} 至 {}（{} 天）</span>'.format(w["since"], w["until"], w["days"])]
    for a in agents.values():
        if not a["found"]:
            continue
        dq = (a.get("data_quality") or {}).get("known_pct")
        chips.append('<span class="chip">{}{} {} · {}{}{}</span>'.format(
            dot(a["id"]), E(a["name"]), E(a["version"] or ""), LEVEL_TEXT.get(a["level"], a["level"]),
            " · {} 个会话".format(a["sessions"]) if a["sessions"] else "",
            " · 记录可识别 {}%".format(dq) if dq is not None and a["sessions"] else ""))
    t = facts["totals"]
    if t.get("automated_sessions"):
        chips.append('<span class="chip">另有 {} 个程序调起的会话未计入</span>'.format(t["automated_sessions"]))
    note = "" if scored["enough_data"] else '<div class="note">会话少于 5 个或消息少于 30 条，暂不给总分</div>'
    o.append('<section id="overview" class="panel hero" style="margin-top:28px">'
             '<div class="score">{ring}<div class="grade">{gl} 级 · {glabel}</div>{delta}{note}</div>'
             '<div><h1>{head}</h1><p class="lead">{summary}</p><div class="meta">{chips}</div>'
             '<div class="vbar" role="img" aria-label="判定分布">{vbar}</div><div class="vlegend">{vleg}</div></div>'
             '<div class="meters">{meters}<div class="small muted">{gn}</div></div></section>'.format(
                 ring=ring(scored["total"]), gl=E(g["letter"]), glabel=E(g["label"]), delta=delta_html, note=note,
                 head=text_or_flag(narrative.get("headline", ""), "narrative.headline", issues),
                 summary=text_or_flag(narrative.get("summary", ""), "narrative.summary", issues),
                 chips="".join(chips), vbar=vbar, vleg=vleg, meters=meters, gn=GRADE_NOTE))
    if issues:
        o.append('<div class="warn">模型写的总评里有 {} 处数字在统计结果里找不到，已用虚线标出，请以下方卡片上的数值为准。</div>'.format(len(issues)))
    for a in agents.values():
        for n in a.get("notes") or []:
            if "无法解压" in n or "出错" in n:
                o.append('<div class="warn">{}：{}</div>'.format(E(a["name"]), E(n)))

    top3 = narrative.get("top3") or []
    if top3:
        o.append('<section><div class="sec-h"><h2>本周就改</h2><p>挑影响最大、最省事的三件</p></div><div class="todo3">')
        for i, s in enumerate(top3[:3]):
            o.append('<div class="panel item"><div class="n">{}</div><div>{}</div></div>'.format(
                i + 1, text_or_flag(s, "narrative.top3[{}]".format(i), issues)))
        o.append("</div></section>")

    # ---------- 复测对比
    if diff and diff.get("total"):
        d = diff["total"]
        imp = "、".join(chk_meta[x["id"]]["title"] for x in diff["improved"] if x["id"] in chk_meta) or "无"
        reg = "、".join(chk_meta[x["id"]]["title"] for x in diff["regressed"] if x["id"] in chk_meta) or "无"
        sec_rows = "".join("<tr><th>{}</th><td>{} → {}（{:+d}）</td></tr>".format(
            E(sections[k]["title"]), v["from"], v["to"], v["delta"]) for k, v in (diff.get("sections") or {}).items() if k in sections)
        o.append('<section><div class="sec-h"><h2>复测对比</h2><p>对比上次体检（{}）</p></div><div class="panel">'
                 '<table class="plain"><tbody><tr><th>总分</th><td><b>{} → {}</b>（{:+d}）</td></tr>{}'
                 '<tr><th>变好的</th><td>{}</td></tr><tr><th>退步的</th><td>{}</td></tr></tbody></table></div></section>'.format(
                     E((diff.get("prev_date") or "")[:10]), d["from"], d["to"], d["delta"], sec_rows, E(imp), E(reg)))

    # ---------- 体检单（矩阵）
    cols = [a["id"] for a in agents.values() if a["found"] and any(a["id"] in r["per_agent"] for r in scored["checks"])]
    o.append('<section id="sheet"><div class="sec-h"><h2>体检单</h2><p>每一项、每个 Agent 一眼看完；点检查项跳到详细诊断</p></div>'
             '<div class="panel matrix-wrap"><table class="matrix"><thead><tr><th>检查项</th>{}</tr></thead><tbody>'.format(
                 "".join("<th>{}{}</th>".format(dot(a), E(AGENT_NAMES.get(a, a))) for a in cols)))
    for sk, sv in sections.items():
        sc = scored["sections"][sk]["score"]
        o.append('<tr class="grp"><td colspan="{}">{} {} · <b>{}</b> 分</td></tr>'.format(
            len(cols) + 1, sk, E(sv["title"]), "—" if sc is None else sc))
        for r in [x for x in scored["checks"] if x["section"] == sk]:
            cells = []
            if set(r["per_agent"]) == {"_global"}:
                x = r["per_agent"]["_global"]
                cells.append('<td colspan="{}"><span class="cell">{}<span class="val">{}</span></span></td>'.format(
                    len(cols), pill(x["verdict"]), E(x["value"])))
            else:
                for aid in cols:
                    x = r["per_agent"].get(aid)
                    if not x:
                        cells.append('<td class="muted">·</td>')
                        continue
                    cells.append('<td><span class="cell" data-tip="{}">{}<span class="val">{}</span></span></td>'.format(
                        E(x["finding"]), pill(x["verdict"], _lab(chk_meta[r["id"]], x["verdict"])), E(x["value"])))
            ref = ' <span class="small muted" title="信号较弱，只展示不计分">参考</span>' if chk_meta[r["id"]].get("scored") is False else ""
            o.append('<tr><td class="t"><span class="id">{}</span><a href="#chk-{}">{}</a>{}</td>{}</tr>'.format(
                r["id"], r["id"], E(r["title"]), ref, "".join(cells)))
    o.append("</tbody></table></div></section>")

    # ---------- 使用画像
    if active:
        n_days = len(active[0].get("daily_messages") or [])
        from datetime import date, timedelta
        start = date.fromisoformat(w["since"])
        day_labels = [(start + timedelta(days=i)).strftime("%m-%d") for i in range(n_days)]
        series = [(a["id"], a["name"], a.get("daily_messages") or [0] * n_days) for a in active]
        hseries = [(a["id"], a["name"], a.get("hourly_messages") or [0] * 24) for a in active]
        legend = "".join('<span>{}{}</span>'.format(dot(a["id"]), E(a["name"])) for a in active) if len(active) > 1 else ""
        busiest = max(range(24), key=lambda h: sum(s[2][h] for s in hseries))
        o.append('<section id="profile"><div class="sec-h"><h2>使用画像</h2><p>你发出的消息按天、按小时分布；鼠标移上去看数值</p></div><div class="charts">')
        o.append('<div class="panel chart"><h3>每天发出的消息</h3><div class="sub">{} 天，共 {} 条</div><div class="legend">{}</div>{}</div>'.format(
            n_days, t["user_messages"], legend, stacked_columns(series, day_labels, "", every=7)))
        o.append('<div class="panel chart"><h3>一天里什么时候在用</h3><div class="sub">最忙的是 {} 点档</div><div class="legend">{}</div>{}</div>'.format(
            busiest, legend, stacked_columns(hseries, [str(h) for h in range(24)], "", every=3, width=420)))
        o.append("</div>")
        # 功能雷达
        feats = checks.get("features") or []
        o.append('<div class="sec-h" style="margin-top:28px"><h2 style="font-size:18px">功能雷达</h2><p>官方推荐的功能，你用了多少次</p></div><div class="radar">')
        for f in feats:
            vals = []
            total = 0
            for a in active:
                if f.get("only") and a["id"] not in f["only"]:
                    continue
                v = a["behavior"].get(f["key"], 0) or 0
                total += v
                vals.append('<span>{}{} <b>{}</b> {}</span>'.format(dot(a["id"]), E(a["name"]), v, E(f["unit"])))
            if not vals:
                continue
            o.append('<div class="feat{}"><div class="name">{}</div><div class="vals">{}</div></div>'.format(
                " zero" if total == 0 else "", E(f["label"]), "".join(vals)))
        o.append("</div></section>")

    # ---------- 详细诊断
    o.append('<section id="detail"><div class="sec-h"><h2>详细诊断</h2><p>先看要改的，做对了的折叠在后面</p></div>')
    order = [("bad", "用错了 / 偏弱"), ("unused", "没用上")]
    for verdict, title in order:
        rs = [r for r in scored["checks"] if r["overall"] == verdict]
        if not rs:
            continue
        o.append('<h3 style="margin:22px 0 12px;font-size:16px">{} <span class="muted num">{} 项</span></h3><div class="cards">'.format(pill(verdict, title), len(rs)))
        for r in rs:
            o.append(_card(r, chk_meta[r["id"]], sections, narrative, issues))
        o.append("</div>")
    goods = [r for r in scored["checks"] if r["overall"] == "good"]
    if goods:
        o.append('<h3 style="margin:26px 0 12px;font-size:16px">{} <span class="muted num">{} 项</span></h3><div class="panel goodlist">'.format(pill("good", "做对了"), len(goods)))
        for r in goods:
            txt = "<br>".join("{}{} {}".format(dot(aid), E(AGENT_NAMES.get(aid, aid)), E(x["finding"])) for aid, x in r["per_agent"].items())
            o.append('<div class="row" id="chk-{}"><b><span class="id">{}</span>{}</b><div class="txt">{}</div></div>'.format(
                r["id"], r["id"], E(r["title"]), txt))
        o.append("</div>")
    rest = [r for r in scored["checks"] if r["overall"] in ("na", "info")]
    if rest:
        o.append('<h3 style="margin:26px 0 12px;font-size:16px">{} <span class="muted num">{} 项</span></h3><div class="cards">'.format(pill("info", "仅供参考 / 数据不足"), len(rest)))
        for r in rest:
            o.append(_card(r, chk_meta[r["id"]], sections, narrative, issues))
        o.append("</div>")
    o.append("</section>")

    # ---------- 配置
    found = [a for a in agents.values() if a["found"]]
    o.append('<section id="config"><div class="sec-h"><h2>配置体检</h2><p>规则文件、Skill、MCP、权限</p></div><div class="panel"><table class="plain"><thead><tr><th></th>{}</tr></thead><tbody>'.format(
        "".join("<th>{}{}</th>".format(dot(a["id"]), E(a["name"])) for a in found)))

    def row(label, fn):
        cells = []
        for a in found:
            try:
                cells.append("<td>{}</td>".format(E(str(fn(a.get("config") or {}, a)))))
            except Exception:
                cells.append("<td>—</td>")
        return "<tr><th>{}</th>{}</tr>".format(E(label), "".join(cells))

    o.append(row("全局规则文件", lambda c, a: "、".join("{} 行".format(v.get("lines", v.get("max_lines", 0))) for v in (c.get("global_rules") or {}).values()) or "无"))
    o.append(row("常用项目有规则文件", lambda c, a: "{} / {}".format((c.get("project_rules") or {}).get("covered", 0), (c.get("project_rules") or {}).get("projects", 0)) if (c.get("project_rules") or {}).get("projects") else "—"))
    o.append(row("最长的规则文件", lambda c, a: "{} 行".format((c.get("project_rules") or {}).get("max_lines", 0))))
    o.append(row("Skill 装了 / 用了", lambda c, a: "{} / {}".format(c.get("skills_installed", 0), c.get("skills_used", 0) if a["sessions"] else "—")))
    o.append(row("MCP 配了 / 闲置", lambda c, a: "{} / {}".format(len(c.get("mcp_configured") or []), len(c.get("mcp_unused") or []) if a["sessions"] else "—")))
    o.append(row("权限", lambda c, a: _perm_text(c, a)))
    o.append(row("hooks", lambda c, a: c.get("hooks", 0)))
    o.append(row("插件", lambda c, a: c.get("plugins", 0)))
    o.append("</tbody></table></div>")
    if active:
        o.append('<div class="grid2" style="margin-top:14px"><div class="panel"><table class="plain"><thead><tr><th>使用习惯</th>{}</tr></thead><tbody>'.format(
            "".join("<th>{}{}</th>".format(dot(a["id"]), E(a["name"])) for a in active)))
        metrics = [
            ("会话 / 消息", lambda a: "{} / {}".format(a["sessions"], a["messages"]["total"])),
            ("消息长度中位数", lambda a: "{} 字".format(int(a["messages"]["median_chars"]))),
            ("单个会话最多消息", lambda a: a["messages"]["per_session_max"]),
            ("自动压缩", lambda a: a["behavior"]["compact_auto"]),
            ("改完代码会验证", lambda a: "{}/{}".format(a["behavior"]["verify_sessions"], a["behavior"]["edit_sessions"])),
            ("缓存命中", lambda a: "{}%".format(a["cache_hit_pct"]) if a["cache_hit_pct"] is not None else "—"),
            ("主力模型", lambda a: next(iter(a["models"]), "—")),
            ("限流 / 接口报错", lambda a: "{} / {}".format(a["errors"].get("rate_limit", 0), sum(v for k, v in a["errors"].items() if k != "rate_limit"))),
        ]
        for label, fn in metrics:
            o.append("<tr><th>{}</th>{}</tr>".format(E(label), "".join("<td>{}</td>".format(E(str(fn(a)))) for a in active)))
        o.append("</tbody></table></div>")
        names = (private or {}).get("project_names") or {}
        o.append('<div class="panel"><table class="plain"><thead><tr><th>项目</th><th>会话</th><th>消息</th></tr></thead><tbody>')
        for p in facts.get("projects") or []:
            lab = p["label"] + ("（{}）".format(names.get(p["label"], "")) if show_projects and names.get(p["label"]) else "")
            o.append("<tr><td>{}{}</td><td>{}</td><td>{}</td></tr>".format(
                E(lab), "" if p.get("active", True) else ' <span class="muted small">临时</span>', p["sessions"], p["messages"]))
        o.append('</tbody></table><div class="small muted" style="padding:0 16px 12px">项目名默认隐藏；本机查看可加 --show-projects。“临时”指应用自动建的目录或只发过一两条消息的项目，不参与规则文件覆盖率。</div></div></div>')
        inv = facts.get("skills_inventory") or {}
        if inv.get("per_dir"):
            o.append('<p class="small muted" style="margin-top:10px">Skill 目录：{}；去重后 {} 个，{} 个在多个目录里各装了一份。</p>'.format(
                E("、".join("{} {} 个".format(k, v) for k, v in inv["per_dir"].items())), inv.get("unique", 0), inv.get("duplicate_count", 0)))
    o.append("</section>")

    # ---------- 改进清单
    actions = pick_actions(scored, checks, facts)
    if actions:
        o.append('<section id="todo"><div class="sec-h"><h2>改进清单</h2><p>按“影响 × 省事”排好了顺序；勾选会记在这个浏览器里。改完一周后说“复测”。</p></div><div class="todo">')
        for i, a in enumerate(actions, 1):
            o.append('<div class="panel col task"><label><input type="checkbox" data-key="{k}"><span><span class="muted num">{n}</span>　{t} <span class="muted small">{ag} · {kind}</span></span></label>{code}<div class="retest">复测看：{rt}</div></div>'.format(
                k=E(a["id"] + "-" + a["agent"]), n=i, t=E(a["title"]), ag=E(AGENT_NAMES.get(a["agent"], a["agent"])),
                kind=RX_KIND.get(a["rx"][0]["kind"], ""), code=code_block(a["rx"][0]), rt=E(a["retest"])))
        o.append('</div><div class="panel" style="margin-top:14px;padding:18px"><h3 style="margin:0 0 4px;font-size:15px">一键交给 Agent</h3>'
                 '<div class="small muted">复制给你的 Agent，它会逐条处理；每改一处配置都会先给你看 diff。</div>{}</div></section>'.format(
                     code_block({"kind": "prompt", "text": fix_prompt(actions)})))

    # ---------- 附录
    ex = facts.get("short_examples") or []
    o.append('<footer id="appendix"><h2 style="font-size:18px;color:var(--ink)">附录</h2><ul>')
    o.append("<li>统计方法：脚本在本机只读扫描会话记录和配置文件，只提取计数、长度、分类；模型只读汇总后的数字，不读原始记录。</li>")
    o.append("<li>程序调起的会话（SDK、exec 等）和子代理会话不计入使用习惯；子代理用到的 Skill、MCP 算“用过”。</li>")
    o.append("<li>“6 字以内的短消息”举例（已脱敏）：{}</li>".format(E("、".join("“{}”×{}".format(e["text"], e["count"]) for e in ex)) if ex else "无"))
    o.append("<li>打分：做对了 1 分、没用上 0.3 分、用错了 0 分，数据不足和仅供参考不计；分区内按检查项权重平均，总分 = 上下文 30% + 任务方法 30% + 配置 20% + 效率 20%；多个 Agent 按会话数加权。</li>")
    o.append("<li>阈值依据官方文档；没有官方数字的是经验值，见 references/metrics.md。</li>")
    o.append("<li>隐私：报告只在本机生成，不上传；项目以“项目 A/B”代称；分享卡不含项目名和路径。原始数字在 facts.json。</li>")
    o.append('<li>生成于 {} · agent-usage-report {} · Python {}</li></ul></footer>'.format(
        E(meta["generated_at"][:16].replace("T", " ")), E(meta["tool_version"]), E(meta["python"])))
    o.append('</div><div id="tip" role="tooltip"></div><script>{}</script></body></html>'.format(JS))
    return "".join(o)


def _card(r, cm, sections, narrative, issues):
    v = r["overall"]
    parts = ['<article class="panel card c-{}" id="chk-{}"><header>{}<h3><span class="id">{}</span>{}</h3><span class="tag">{}</span></header>'.format(
        v, r["id"], pill(v, _lab(cm, v)), r["id"], E(r["title"]), E(sections[r["section"]]["title"]))]
    rank = {"bad": 0, "unused": 1, "info": 2, "good": 3, "na": 4}
    for aid, x in sorted(r["per_agent"].items(), key=lambda kv: rank.get(kv[1]["verdict"], 5)):
        ftxt = (narrative.get("findings") or {}).get(r["id"]) if len(r["per_agent"]) == 1 else None
        body = text_or_flag(ftxt, "narrative.findings." + r["id"], issues) if ftxt else E(x["finding"])
        ev = "".join("<li>{}</li>".format(E(e)) for e in x.get("evidence") or [])
        note = '<div class="small muted">{}</div>'.format(E(x["note"])) if x.get("note") else ""
        parts.append('<div class="ag"><div class="who">{}{} {}</div><div class="big">{}</div><p>{}</p>{}{}</div>'.format(
            dot(aid), E(AGENT_NAMES.get(aid, aid)), pill(x["verdict"], _lab(cm, x["verdict"])) if len(r["per_agent"]) > 1 else "",
            E(x["value"]), body, '<ul class="ev">{}</ul>'.format(ev) if ev else "", note))
    bas = []
    for aid in r["per_agent"]:
        b = (cm.get("basis") or {}).get(aid)
        if b:
            bas.append('{}：<a href="{}" target="_blank" rel="noopener">{}</a>'.format(E(AGENT_NAMES.get(aid, aid)), E(b["url"]), E(b["point"])))
    if bas:
        parts.append('<div class="basis">官方依据 · ' + "<br>".join(bas) + "</div>")
    if v in ("bad", "unused", "info"):
        blocks = []
        for aid, x in r["per_agent"].items():
            rxl = (cm.get("rx") or {}).get(aid)
            if rxl and x["verdict"] in ("bad", "unused", "info"):
                head = '<div class="small" style="margin-top:6px">{}<b>{}</b></div>'.format(dot(aid), E(AGENT_NAMES.get(aid, aid))) if len(r["per_agent"]) > 1 else ""
                blocks.append(head + "".join(code_block(rx) for rx in rxl))
        if blocks:
            parts.append('<details class="rx"{}><summary>怎么改</summary>{}<div class="retest">复测看：{}</div></details>'.format(
                " open" if v == "bad" else "", "".join(blocks), E(cm.get("retest", ""))))
    parts.append("</article>")
    return "".join(parts)


def _lab(cm, verdict):
    """结果类检查（E 区）用“表现好 / 偏弱”，不说“做对了 / 用错了”。"""
    return (cm.get("labels") or {}).get(verdict)


def _perm_text(c, a):
    p = c.get("permissions") or {}
    if "approval_policy" in p:
        modes = a.get("modes") or {}
        if modes:
            top = max(modes.items(), key=lambda kv: kv[1])[0]
            return "实际最常用 {}".format(top)
        return "{} / {}".format(p.get("approval_policy") or "默认", p.get("sandbox_mode") or "默认")
    if "approval_mode" in p:
        return "白名单 {} 条".format(p.get("allow", 0))
    modes = a.get("modes") or {}
    top = max(modes.items(), key=lambda kv: kv[1])[0] if modes else None
    return "白名单 {} 条{}".format(c.get("allow_rules_total", 0), " · 常用 " + top if top else "")
