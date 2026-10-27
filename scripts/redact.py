"""脱敏：报告里允许出现的少量文字例子，必须先过这里。"""
from __future__ import annotations

import hashlib
import re

_RULES = [
    (re.compile(r"https?://\S+"), "〔链接〕"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "〔邮箱〕"),
    (re.compile(r"(?:~|/Users|/home|[A-Za-z]:\\)[^\s'\"]*"), "〔路径〕"),
    (re.compile(r"(?:\.{0,2}/)?(?:[\w.-]+/){1,}[\w.-]+"), "〔路径〕"),
    (re.compile(r"\b(?:sk|ghp|gho|xox[abp]|AKIA|AIza)[\w-]{8,}"), "〔密钥〕"),
    (re.compile(r"\b[A-Za-z0-9_-]{24,}\b"), "〔长串〕"),
    (re.compile(r"\d{5,}"), "〔数字〕"),
]


def redact(text: str) -> str:
    out = text
    for pat, rep in _RULES:
        out = pat.sub(rep, out)
    return out


def project_key(path: str, salt: str) -> str:
    return hashlib.sha256((salt + "\0" + path).encode("utf-8")).hexdigest()[:10]


def project_label(i: int) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "项目 " + (letters[i] if i < 26 else str(i + 1))


# 分享卡最后一道闸：出现这些就拒绝输出
_CARD_FORBIDDEN = re.compile(r"(/Users/|/home/|~/|[A-Za-z]:\\|\\\\|@[\w.-]+|https?://|\.(?:md|py|ts|js|json)\b)")


def card_text_safe(text: str, extra_forbidden=()) -> bool:
    if _CARD_FORBIDDEN.search(text):
        return False
    low = text.lower()
    for word in extra_forbidden:
        w = (word or "").strip().lower()
        if len(w) >= 3 and w in low:
            return False
    return True
