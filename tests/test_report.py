import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402
from collectors.base import classify_command, is_code_path, zstd_available  # noqa: E402
from collectors.claude_code import ClaudeCodeCollector  # noqa: E402
from collectors.codex import CodexCollector, _mini_toml  # noqa: E402
import redact  # noqa: E402
import render  # noqa: E402
import score  # noqa: E402

SCAN = ROOT / "scripts" / "scan.py"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 不能放在系统临时目录：/var/folders 这类路径会被当成“应用自动建的临时目录”过滤掉
        base = ROOT / "tests" / ".tmp"
        base.mkdir(exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="aur-test-", dir=str(base)))
        cls.fx = fixtures.build_home(cls.tmp)
        cls.home = cls.fx["home"]
        cls.until = fixtures.NOW + timedelta(minutes=1)
        cls.since = fixtures.NOW - timedelta(days=30)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestClaudeCode(Base):
    def setUp(self):
        self.c = ClaudeCodeCollector(self.home)
        ss = self.c.collect(self.since, self.until)
        self.main = {s.session_id: s for s in ss if not s.is_subagent}
        self.subs = [s for s in ss if s.is_subagent]

    def test_user_messages_exclude_synthetic(self):
        s = self.main["11111111-aaaa"]
        # 手打两条 + 工作中追加一条；斜杠命令、打断、任务通知、isMeta、工具结果都不算
        self.assertEqual(s.user_msgs, 3)
        self.assertEqual(s.slash["clear"], 1)
        self.assertEqual(s.slash["model"], 1)
        self.assertEqual(s.interrupts, 1)

    def test_tools_and_flags(self):
        s = self.main["11111111-aaaa"]
        self.assertEqual(s.compact_auto, 1)
        self.assertTrue(s.plan_used)
        self.assertEqual(s.subagent_calls, 1)
        self.assertEqual(s.ask_user, 1)
        self.assertEqual(s.mcp_servers["notion"], 1)
        self.assertEqual(s.skills["01-writer-dir"], 1)
        self.assertTrue(s.verify_after_edit)
        self.assertEqual(s.code_edits, 1)
        self.assertEqual(s.errors["rate_limit"], 1)
        self.assertEqual(s.unknown_lines, 1)

    def test_usage_deduped_by_message_id(self):
        s = self.main["11111111-aaaa"]
        self.assertEqual(s.models["claude-opus-5-5"], 2)
        self.assertEqual(s.tok_input, 30)
        self.assertEqual(s.tok_cache_read, 2700)

    def test_window_and_correction_loop(self):
        s = self.main["22222222-bbbb"]
        self.assertEqual(s.user_msgs, 4)  # 60 天前那条在窗口外
        self.assertEqual(s.neg_loops, 1)
        self.assertEqual(s.modes["bypassPermissions"], 4)
        self.assertEqual(s.code_edits, 0)  # 只改了 .md

    def test_subagent_file(self):
        self.assertEqual(len(self.subs), 1)
        self.assertEqual(self.subs[0].user_msgs, 0)

    def test_config(self):
        cfg = self.c.read_config([str(self.fx["proj_a"]), str(self.fx["proj_b"])])
        self.assertEqual(cfg["desktop_plugin_skills"], [])  # 窗口内的会话都不是桌面版
        self.assertEqual(cfg["permissions"]["allow"], 1)
        self.assertEqual(cfg["hooks"], 1)
        self.assertEqual(sorted(cfg["mcp"]["user"]), ["github", "notion"])
        pa = cfg["projects"][str(self.fx["proj_a"])]
        names = sorted(f["name"] for f in pa["rule_files"])
        self.assertEqual(names, ["AGENTS.md", "CLAUDE.md"])
        self.assertEqual(sum(f["secrets"] for f in pa["rule_files"]), 1)
        self.assertEqual(cfg["projects"][str(self.fx["proj_b"])]["rule_files"], [])

    def test_desktop_plugin_skills(self):
        c = ClaudeCodeCollector(self.home)
        c.collect(self.since - timedelta(days=60), self.until)  # 把桌面版的那条旧消息也纳入
        self.assertTrue(c.desktop_used)
        self.assertEqual(c.read_config([])["desktop_plugin_skills"], ["standup"])


class TestCodex(Base):
    def setUp(self):
        self.c = CodexCollector(self.home)
        ss = self.c.collect(self.since, self.until)
        self.main = {s.session_id: s for s in ss if not s.is_subagent}
        self.subs = [s for s in ss if s.is_subagent]

    def test_new_format(self):
        s = self.main["cx-new"]
        self.assertEqual(s.user_msgs, 1)  # 注入的 AGENTS.md 不算
        self.assertEqual(s.skills["playwright"], 2)  # $提及 + 读 SKILL.md
        self.assertEqual(s.edits, 2)
        self.assertEqual(s.code_edits, 1)
        self.assertTrue(s.verify_after_edit)
        self.assertEqual(s.subagent_calls, 1)
        self.assertTrue(s.review_used)
        self.assertEqual(s.compact_auto, 1)
        self.assertEqual(s.interrupts, 1)
        self.assertTrue(s.goal_used)
        self.assertTrue(s.plan_used)
        self.assertEqual(s.tok_cache_read, 900)
        self.assertEqual(s.tok_input, 100)
        self.assertEqual(s.modes["never/danger-full-access"], 1)
        self.assertEqual(s.entrypoint, "Codex Desktop")

    def test_old_format_and_zst(self):
        if self.fx["zst"] and not zstd_available():
            self.skipTest("没有 zstd")
        s = self.main["cx-old"]
        self.assertEqual(s.user_msgs, 1)
        self.assertEqual(s.cmd_families["test"], 1)
        self.assertEqual(s.code_edits, 1)
        self.assertTrue(s.verify_after_edit)

    def test_subagent_session(self):
        self.assertEqual(len(self.subs), 1)

    def test_config(self):
        cfg = self.c.read_config([str(self.fx["proj_a"])])
        self.assertEqual(cfg["permissions"]["approval_policy"], "never")
        self.assertEqual(cfg["mcp"]["user"], ["node_repl"])
        self.assertEqual(cfg["plugins"], 1)
        self.assertIn("playwright", cfg["skills"])
        self.assertEqual(cfg["projects"][str(self.fx["proj_a"])]["rule_files"][0]["name"], "AGENTS.md")


class TestEndToEnd(Base):
    def run_scan(self, *args):
        out = self.tmp / "out"
        r = subprocess.run([sys.executable, str(SCAN), "--home", str(self.home), "--out", str(out)] + list(args),
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return out, json.loads(r.stdout)

    def test_run_render_and_privacy(self):
        out, res = self.run_scan("run")
        latest = out / "latest"
        for f in ("facts.json", "findings.json", "report.html", "share-card-x.svg", "share-card-xhs.svg", "share-card.html", "private.json"):
            self.assertTrue((latest / f).exists(), f)
        self.assertEqual(res["sessions"], 5)  # canvas-agent 那个自动会话不算
        secret = self.fx["secret"]
        for f in ("facts.json", "findings.json", "report.html", "share-card-x.svg", "share-card-xhs.svg", "share-card.html"):
            text = (latest / f).read_text(encoding="utf-8")
            self.assertNotIn(secret, text, f)
            self.assertNotIn(str(self.tmp), text, f)
        self.assertIn(secret, (latest / "private.json").read_text(encoding="utf-8"))
        findings = json.loads((latest / "findings.json").read_text(encoding="utf-8"))
        ids = {c["id"] for c in findings["checks"]}
        self.assertTrue({"A1", "B2", "C1", "C3", "C6", "D2"} <= ids)
        c6 = next(c for c in findings["checks"] if c["id"] == "C6")
        self.assertEqual(c6["agents"]["codex"]["verdict"], "bad")
        c2 = next(c for c in findings["checks"] if c["id"] == "C2")
        self.assertEqual(c2["agents"]["cursor"]["verdict"], "bad")  # 600 行的规则
        facts = json.loads((latest / "facts.json").read_text(encoding="utf-8"))
        self.assertEqual(facts["totals"]["automated_sessions"], 1)
        self.assertEqual(len(facts["agents"]["claude_code"]["hourly_messages"]), 24)
        self.assertEqual(sum(facts["agents"]["claude_code"]["daily_messages"]), facts["agents"]["claude_code"]["messages"]["total"])
        c1 = next(c for c in findings["checks"] if c["id"] == "C1")
        # 项目 B 只有 1 个会话、4 条消息，不算“常用项目”，不该拉低覆盖率
        self.assertEqual(c1["agents"]["claude_code"]["value"], "1/1 个项目")
        a1 = next(c for c in findings["checks"] if c["id"] == "A1")
        self.assertIn("evidence", a1["agents"]["codex"])
        html_text = (latest / "report.html").read_text(encoding="utf-8")
        for anchor in ('id="sheet"', 'id="profile"', 'id="detail"', 'id="todo"', 'data-tip='):
            self.assertIn(anchor, html_text)
        c8 = next(c for c in findings["checks"] if c["id"] == "C8")
        self.assertEqual(c8["agents"]["claude_code"]["verdict"], "bad")

        # 模型写的总评：编造的数字要被标出来
        narr = {"headline": "会话 4 个，问题不少", "summary": "缓存命中 7777%", "top3": ["先 /clear"], "card_quote": "清空上下文"}
        (latest / "narrative.json").write_text(json.dumps(narr, ensure_ascii=False), encoding="utf-8")
        _, res2 = self.run_scan("render", "--narrative", str(latest / "narrative.json"))
        self.assertIn("narrative.summary", res2["unverified_numbers"])
        self.assertNotIn("narrative.headline", res2["unverified_numbers"])
        self.assertIn("unverified", (latest / "report.html").read_text(encoding="utf-8"))
        self.assertIn("清空上下文", (latest / "share-card-x.svg").read_text(encoding="utf-8"))

        # 分享卡金句里出现项目名：拒绝放进卡片
        narr["card_quote"] = "我在 " + secret + " 上翻车"
        (latest / "narrative.json").write_text(json.dumps(narr, ensure_ascii=False), encoding="utf-8")
        self.run_scan("render", "--narrative", str(latest / "narrative.json"))
        self.assertNotIn(secret, (latest / "share-card-x.svg").read_text(encoding="utf-8"))

    def test_detect(self):
        _, res = self.run_scan("detect")
        found = {x["agent"]: x for x in res}
        self.assertTrue(found["claude_code"]["found"])
        self.assertEqual(found["cursor"]["level"], "config")


class TestPieces(unittest.TestCase):
    def test_redact(self):
        r = redact.redact("看 /Users/me/proj/a.py 和 https://x.com/a 发 me@x.com 还有 sk-abcdefghijklmnopqrstuv")
        self.assertNotIn("/Users", r)
        self.assertNotIn("https", r)
        self.assertNotIn("me@x.com", r)
        self.assertNotIn("sk-abc", r)

    def test_card_guard(self):
        self.assertFalse(redact.card_text_safe("我的项目在 /Users/me/x"))
        self.assertFalse(redact.card_text_safe("alpha 项目", ["alpha"]))
        self.assertTrue(redact.card_text_safe("做对 10 项"))

    def test_classify(self):
        self.assertEqual(classify_command("npm run test -- --watch=false"), "test")
        self.assertEqual(classify_command("pnpm build"), "build")
        self.assertEqual(classify_command("npx eslint ."), "lint")
        self.assertEqual(classify_command("git status"), "git")
        self.assertTrue(is_code_path("a/b.tsx"))
        self.assertFalse(is_code_path("a/b.md"))

    def test_mini_toml(self):
        p = Path(tempfile.mkdtemp()) / "c.toml"
        p.write_text('approval_policy = "never"  # x\n[mcp_servers.a]\ncommand = "n"\n[plugins."g@o"]\nenabled = false\n')
        d = _mini_toml(p)
        self.assertEqual(d["approval_policy"], "never")
        self.assertIn("a", d["mcp_servers"])
        self.assertFalse(d["plugins"]["g@o"]["enabled"])

    def test_numbers(self):
        allowed = render.allowed_numbers({"a": 98.3, "b": 47})
        self.assertEqual(render.unverified_numbers("命中 98.3%，47 个，3 件事", allowed), [])
        self.assertEqual(render.unverified_numbers("命中 99%", allowed), ["99"])

    def test_diff(self):
        prev = {"generated_at": "x", "total": 60, "sections": {"A": 50}, "checks": {"A1": "bad", "B1": "good"}}
        cur = {"total": 70, "sections": {"A": 65}, "checks": {"A1": "good", "B1": "unused"}}
        d = score.diff(prev, cur)
        self.assertEqual(d["total"]["delta"], 10)
        self.assertEqual([x["id"] for x in d["improved"]], ["A1"])
        self.assertEqual([x["id"] for x in d["regressed"]], ["B1"])

    def test_no_network_imports(self):
        bad = re.compile(r"^\s*(import|from)\s+(urllib|http|socket|requests|ftplib|smtplib|ssl)\b", re.M)
        for f in (ROOT / "scripts").rglob("*.py"):
            self.assertIsNone(bad.search(f.read_text(encoding="utf-8")), str(f))


if __name__ == "__main__":
    unittest.main()
