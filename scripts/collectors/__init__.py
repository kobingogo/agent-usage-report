"""各 Agent 的采集器。新增产品：写一个 Collector 子类并加进 ALL。"""
from .claude_code import ClaudeCodeCollector
from .codex import CodexCollector
from .cursor_config import CursorConfigCollector

ALL = [ClaudeCodeCollector, CodexCollector, CursorConfigCollector]
