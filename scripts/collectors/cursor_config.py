"""Cursor：第一版只体检配置，不分析会话。

原因：会话主库 state.vscdb 是未公开的内部格式；~/.cursor/projects/*/agent-transcripts 只是导出副本，
没有时间戳、模型和 token，IDE 里的会话也可能不在其中。
"""
from __future__ import annotations

from pathlib import Path

from .base import Collector, Detection, dir_size, list_skills, load_json, rule_file_info


class CursorConfigCollector(Collector):
    id = "cursor"
    display_name = "Cursor"

    def __init__(self, home: Path):
        super().__init__(home)
        self.root = home / ".cursor"

    def detect(self) -> Detection:
        det = Detection(self.id, self.display_name, self.root.is_dir())
        if det.found:
            det.paths = [str(self.root)]
            det.size_bytes = dir_size([self.root / "rules", self.root / "skills"])
            det.level = "config"
            det.notes.append("第一版只体检配置；会话记录是未公开的内部格式，暂不分析")
        return det

    def read_config(self, project_paths: list) -> dict:
        cfg = {"agent": self.id, "rules": {}, "skills": [], "mcp": {}, "permissions": {}, "hooks": 0, "projects": {}}
        rd = self.root / "rules"
        if rd.is_dir():
            files = [f for f in rd.rglob("*.mdc")]
            infos = [rule_file_info(f) for f in files]
            cfg["rules"]["global_rules_dir"] = {
                "files": len(files),
                "lines": sum(i["lines"] for i in infos),
                "max_lines": max([i["lines"] for i in infos] or [0]),
                "secrets": sum(i["secrets"] for i in infos),
            }
        cfg["skills"] = sorted({n for n, _ in list_skills(self.root / "skills")})
        mj = load_json(self.root / "mcp.json") or {}
        cfg["mcp"] = {"user": sorted((mj.get("mcpServers") or {}).keys()), "project": {}}
        cli = load_json(self.root / "cli-config.json") or {}
        perms = cli.get("permissions") or {}
        cfg["permissions"] = {"allow": len(perms.get("allow") or []), "deny": len(perms.get("deny") or []),
                              "approval_mode": cli.get("approvalMode")}
        hj = load_json(self.root / "hooks.json") or {}
        cfg["hooks"] = sum(len(v) if isinstance(v, list) else 1 for v in (hj.get("hooks") or {}).values())
        for p in project_paths:
            pp = Path(p)
            if not pp.is_dir():
                continue
            prd = pp / ".cursor" / "rules"
            if prd.is_dir():
                files = list(prd.rglob("*.mdc"))
                cfg["projects"][p] = {"rule_files": [{"name": ".cursor/rules/" + f.name, **rule_file_info(f)} for f in files]}
        return cfg
