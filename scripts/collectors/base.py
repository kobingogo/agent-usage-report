"""采集器的公共部分：统一的会话统计结构、通用分类规则、只读文件工具。

采集器只产出计数和分类，不保存提示词、代码或命令原文。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


# ---------- 通用分类 ----------

SHORT_MSG_CHARS = 6  # “可以”“继续”这类短消息的上限

# 返工信号：用户在指出“结果不对”。只看消息前 40 个字，先排除正面说法。
_REWORK_POS = re.compile(r"(没问题|没毛病|太棒|太好了|不错|很好|完美|搞定了|可以了|我(说|发|写|打)错|发错了|works now|looks good|perfect)", re.IGNORECASE)
_REWORK = re.compile(
    r"(不对|不行|不是这样|错了|有问题|有bug|报错|出错|失败|没生效|不生效|没反应|没变化|没效果|不起作用|跑不起来|打不开|"
    r"不满意|不太(行|好|对|合适|像|自然)|不够|太差|质量差|不好看|难看|简陋|空白|没有.{0,10}(感觉|效果)了|太(素|单调|糊|暗|亮|慢|丑|乱|假|生硬|突兀|夸张|简陋)|有点(糊|粗糙|怪|奇怪|假|乱|丑|生硬|问题)|"
    r"还有(问题|bug|瑕疵)|漏了|缺了|少了|没(动|飘|生成|出来|加上|改)|你是不是(选错|搞错|弄错|漏|忘)|搞错|弄错|"
    r"重做|重来|回滚|改回|撤销|退回|"
    r"看不到|显示不了|没显示|白屏|黑屏|崩了|卡住|卡着|一直在|还是没|还是不|还是有|还是报|还是一样|还是老样子|(依然|仍然)(不|没|有问题|报错|失败)|"
    r"又出现|又报|又坏|怎么还|怎么又|^为什么.{0,12}(不|没|还|这么|那么|卡|慢|会)|不是.{0,16}(而是|我要|我想要|我说的)|"
    r"\bstill (not|broken|fail|wrong|the same)|doesn'?t work|not working|\bwrong\b|\bbroken\b|\bfailed\b|"
    r"why (is|does|did|isn'?t|doesn'?t|didn'?t)\b.{0,20}\bnot\b)",
    re.IGNORECASE,
)


_REWORK_STRONG = re.compile(r"(报错|失败|不对|不行|还是不|还是没|还是有|白屏|黑屏|崩了)")
_CONDITIONAL = re.compile(r"(如果|若是|是否|有没有|会不会|能否|能不能|万一)")


def is_rework(text: str) -> bool:
    """近似识别“用户在指出结果不对”。在作者数据上抽样，准确率约八成；只用于看比例和趋势。"""
    head = text.strip()[:40]
    if _REWORK_POS.search(head):
        return False
    if not _REWORK.search(head):
        return False
    # “如果觉得不够……”“是否可以……”这类条件句和提问，除非带强信号，否则不算
    if _CONDITIONAL.search(head) and not _REWORK_STRONG.search(head):
        return False
    return True


_FILE_REF = re.compile(
    r"(@[\w./-]+|[\w一-鿿-]+\.(py|ts|tsx|js|jsx|mjs|md|json|html|css|scss|go|rs|java|swift|kt|"
    r"ya?ml|toml|sh|vue|svelte|rb|php|c|cc|cpp|h|sql|txt|csv)\b|(?:^|\s)(?:\.{0,2}/|~/)[\w.-]+/)",
    re.IGNORECASE,
)

_TEST = re.compile(
    r"\b(pytest|jest|vitest|mocha|go test|cargo test|(?:npm|pnpm|yarn|bun)(?: run)? test|"
    r"playwright test|unittest|rspec|phpunit|xcodebuild test|swift test|deno test|ctest)\b"
)
_BUILD = re.compile(
    r"\b((?:npm|pnpm|yarn|bun)(?: run)? build|vite build|next build|tsc\b|cargo (?:build|check)|go build|"
    r"xcodebuild|gradle|mvn|make\b|swift build|hugo|astro build|webpack)"
)
_LINT = re.compile(
    r"\b(eslint|ruff|flake8|pylint|prettier --check|(?:npm|pnpm|yarn|bun)(?: run)? (?:lint|typecheck|check)|"
    r"biome|golangci|clippy|mypy|pyright|tsc --noEmit|stylelint|shellcheck)\b"
)


def classify_message(text: str) -> dict:
    t = text.strip()
    return {
        "chars": len(t),
        "short": len(t) <= SHORT_MSG_CHARS,
        "neg": is_rework(t),
        "file_ref": bool(_FILE_REF.search(t)),
    }


def classify_command(cmd: str) -> str:
    if _TEST.search(cmd):
        return "test"
    if _LINT.search(cmd):
        return "lint"
    if _BUILD.search(cmd):
        return "build"
    if re.match(r"\s*git\s", cmd):
        return "git"
    return "other"


VERIFY_FAMILIES = {"test", "lint", "build"}

_DOC_EXT = {"md", "markdown", "mdx", "txt", "rst", "csv", "tsv", "docx", "doc", "pdf", "png", "jpg", "jpeg",
            "gif", "webp", "mp3", "mp4", "wav", "pptx", "xlsx", "srt", "vtt"}
ACTIVE_BUCKET_SECONDS = 1800  # 并行会话按 30 分钟时间片统计


def is_code_path(path: str) -> bool:
    """改的是不是代码文件（文档、图片、表格不算）。没有扩展名的按代码算。"""
    name = str(path or "").rsplit("/", 1)[-1]
    if "." not in name:
        return True
    return name.rsplit(".", 1)[-1].lower() not in _DOC_EXT


def model_tier(model: str) -> str:
    m = (model or "").lower()
    if any(k in m for k in ("opus", "fable")):
        return "top"
    if "sonnet" in m:
        return "mid"
    if "haiku" in m:
        return "small"
    return "other"


# ---------- 会话统计 ----------

@dataclass
class SessionStats:
    agent: str
    session_id: str
    entrypoint: str = "unknown"
    project_path: str = ""
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    is_subagent: bool = False
    automated: bool = False  # 程序调起的会话（SDK、exec、canvas 等），不计入使用习惯
    version: str = ""
    level: str = "full"  # full：逐条记录；session：只有会话级元数据（如 Codex 解不开的 .zst）

    # 用户消息
    user_msgs: int = 0
    user_chars: list = field(default_factory=list)
    short_msgs: int = 0
    short_texts: Counter = field(default_factory=Counter)  # 仅 ≤12 字的短消息，用于脱敏举例
    msg_days: Counter = field(default_factory=Counter)     # 本地日期 → 消息数
    msg_hours: Counter = field(default_factory=Counter)    # 本地小时 → 消息数
    file_ref_msgs: int = 0
    max_neg_run: int = 0
    rework_msgs: int = 0
    rework_days: Counter = field(default_factory=Counter)
    neg_loops: int = 0  # 连续 ≥3 条否定开头的消息出现的次数
    _neg_run: int = 0

    slash: Counter = field(default_factory=Counter)
    tools: Counter = field(default_factory=Counter)        # 按工具名
    tool_cats: Counter = field(default_factory=Counter)    # 按类别
    skills: Counter = field(default_factory=Counter)
    mcp_servers: Counter = field(default_factory=Counter)
    cmd_families: Counter = field(default_factory=Counter)
    modes: Counter = field(default_factory=Counter)        # 权限 / 协作模式（按用户轮次）
    models: Counter = field(default_factory=Counter)       # 按助手消息
    efforts: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)

    interrupts: int = 0
    compact_auto: int = 0
    compact_manual: int = 0
    edits: int = 0
    code_edits: int = 0
    active_buckets: set = field(default_factory=set)
    verify_after_edit: bool = False
    plan_used: bool = False
    goal_used: bool = False
    subagent_calls: int = 0
    ask_user: int = 0
    review_used: bool = False
    worktree: bool = False

    tok_input: int = 0
    tok_output: int = 0
    tok_cache_read: int = 0
    tok_cache_write: int = 0

    unknown_lines: int = 0
    total_lines: int = 0

    def add_user_message(self, text: str, ts: Optional[datetime] = None) -> None:
        c = classify_message(text)
        self.user_msgs += 1
        if ts is not None:
            local = ts.astimezone()
            self.msg_days[local.date().isoformat()] += 1
            self.msg_hours[local.hour] += 1
        self.user_chars.append(c["chars"])
        if c["short"]:
            self.short_msgs += 1
        if c["chars"] <= 12:
            self.short_texts[text.strip()] += 1
        if c["file_ref"]:
            self.file_ref_msgs += 1
        if c["neg"]:
            self.rework_msgs += 1
            if ts is not None:
                self.rework_days[ts.astimezone().date().isoformat()] += 1
            self._neg_run += 1
            if self._neg_run == 3:
                self.neg_loops += 1
            self.max_neg_run = max(self.max_neg_run, self._neg_run)
        else:
            self._neg_run = 0

    def add_command(self, cmd: str) -> None:
        fam = classify_command(cmd)
        self.cmd_families[fam] += 1
        if fam in VERIFY_FAMILIES and self.edits:
            self.verify_after_edit = True

    def touch(self, ts: Optional[datetime]) -> None:
        if ts is None:
            return
        self.active_buckets.add(int(ts.timestamp() // ACTIVE_BUCKET_SECONDS))
        if self.start is None or ts < self.start:
            self.start = ts
        if self.end is None or ts > self.end:
            self.end = ts

    def to_dict(self) -> dict:
        d = {}
        for k, v in self.__dict__.items():
            if k.startswith("_"):
                continue
            if isinstance(v, datetime):
                v = v.isoformat()
            elif isinstance(v, Counter):
                v = dict(v)
            elif isinstance(v, set):
                v = sorted(v)
            d[k] = v
        return d


@dataclass
class Detection:
    agent: str
    display_name: str
    found: bool
    paths: list = field(default_factory=list)
    size_bytes: int = 0
    version: str = ""
    level: str = "none"  # full / session / config / none
    notes: list = field(default_factory=list)


# ---------- 工具函数 ----------

def parse_ts(v) -> Optional[datetime]:
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)):
            if v > 1e12:
                v = v / 1000.0
            return datetime.fromtimestamp(v, tz=timezone.utc)
        s = str(v)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OverflowError, OSError):
        return None


def dir_size(paths) -> int:
    total = 0
    for p in paths:
        p = Path(p)
        if p.is_file():
            total += p.stat().st_size
            continue
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return total


def read_jsonl(path: Path) -> Iterator[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            yield line


def zstd_lines(path: Path) -> Optional[Iterator[str]]:
    """读 .zst 文件。依次尝试：标准库 compression.zstd（3.14+）→ 系统 zstd 命令。都不行返回 None。"""
    try:
        from compression import zstd  # type: ignore

        data = zstd.decompress(path.read_bytes())
        return iter(data.decode("utf-8", "replace").splitlines())
    except ImportError:
        pass
    except Exception:
        return None
    try:
        out = subprocess.run(["zstd", "-dc", str(path)], capture_output=True, timeout=60)
        if out.returncode == 0:
            return iter(out.stdout.decode("utf-8", "replace").splitlines())
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def zstd_available() -> bool:
    try:
        from compression import zstd  # type: ignore  # noqa: F401

        return True
    except ImportError:
        pass
    try:
        return subprocess.run(["zstd", "--version"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def sqlite_ro(path: Path) -> Optional[sqlite3.Connection]:
    try:
        uri = "file:" + str(path) + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=2)
        con.execute("select 1")
        return con
    except sqlite3.Error:
        return None


def load_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def count_lines(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def skill_name(skill_md: Path) -> str:
    """读 SKILL.md 的 frontmatter name，读不到就用目录名。只读前 20 行。"""
    try:
        with open(skill_md, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                m = re.match(r"^name:\s*['\"]?([^'\"\n]+)", line)
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    return skill_md.parent.name


def list_skills(root: Path) -> list:
    """返回 [(name, path)]，root 下每个含 SKILL.md 的子目录算一个。"""
    out = []
    if not root.is_dir():
        return out
    try:
        for child in sorted(root.iterdir()):
            if child.name.startswith("."):
                continue
            md = child / "SKILL.md"
            if md.is_file():
                out.append((skill_name(md), str(child)))
    except OSError:
        pass
    return out


SECRET_PATTERNS = re.compile(
    r"(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|"
    r"xox[abp]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|"
    r"(?i:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,})"
)


def rule_file_info(path: Path) -> dict:
    """规则文件只取体量和是否疑似含密钥，不取内容。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"lines": 0, "bytes": 0, "secrets": 0}
    return {
        "lines": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
        "bytes": len(text.encode("utf-8")),
        "secrets": len(SECRET_PATTERNS.findall(text)),
    }


def ancestors_until_home(start: Path, home: Path) -> list:
    """从项目目录往上走，到 home 为止（不含 home），用于找父目录里的规则文件。"""
    out = []
    try:
        p = start.resolve()
        h = home.resolve()
    except OSError:
        return out
    while True:
        if p == h or p == p.parent:
            break
        out.append(p)
        p = p.parent
    return out


class Collector:
    id = "base"
    display_name = "Base"

    def __init__(self, home: Path):
        self.home = home

    def detect(self) -> Detection:
        raise NotImplementedError

    def collect(self, since: datetime, until: datetime) -> list:
        """返回 SessionStats 列表（含子代理会话，is_subagent=True）。"""
        return []

    def read_config(self, project_paths: list) -> dict:
        return {}
