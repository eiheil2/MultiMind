"""代码搜索 Skill — 自研核心能力。"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from multimind.skills.base import Skill, SkillManifest, SkillResult
from multimind.skills.core.manifests import CODE_SEARCH_MANIFEST

__all__ = ["CodeSearchSkill"]

logger = logging.getLogger(__name__)


class CodeSearchSkill(Skill):
    """代码库搜索 Skill。

    Args:
        pattern: 搜索模式（正则）。
        path: 搜索路径（可选，默认当前目录）。
        glob: 文件名 glob 过滤（可选，如 ``*.py``）。
        mode: 搜索模式（``grep`` / ``glob`` / ``content``）。
    """

    def __init__(self, manifest: SkillManifest | None = None) -> None:
        super().__init__(manifest or CODE_SEARCH_MANIFEST)

    async def execute(self, args: dict[str, Any]) -> SkillResult:
        pattern = args.get("pattern", "")
        if not pattern:
            return SkillResult(success=False, error="missing 'pattern' argument")

        path = args.get("path", ".")
        mode = args.get("mode", "grep")

        try:
            if mode == "glob":
                # glob 模式：按文件名匹配
                matched = sorted(Path(path).rglob(pattern))
                output = "\n".join(str(p) for p in matched[:100])
                return SkillResult(
                    success=True,
                    output=output or "no matches",
                    metadata={"mode": "glob", "count": len(matched)},
                )

            # grep 模式：按内容搜索
            glob_filter = args.get("glob", "")
            cmd = ["grep", "-rn", "--color=never", pattern]
            if glob_filter:
                cmd.extend(["--include", glob_filter])
            cmd.append(path)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout[:10000] if result.stdout else "no matches"
            return SkillResult(
                success=True,
                output=output,
                metadata={
                    "mode": "grep",
                    "pattern": pattern,
                    "returncode": result.returncode,
                },
            )
        except subprocess.TimeoutExpired:
            return SkillResult(success=False, error="search timed out (30s)")
        except Exception as e:
            return SkillResult(success=False, error=str(e))
