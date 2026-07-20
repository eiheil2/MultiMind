"""文件读写 Skill — 自研核心能力。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from multimind.skills.base import Skill, SkillManifest, SkillResult
from multimind.skills.core.manifests import FILE_READ_MANIFEST, FILE_WRITE_MANIFEST

__all__ = ["FileReadSkill", "FileWriteSkill"]

logger = logging.getLogger(__name__)


class FileReadSkill(Skill):
    """文件读取 Skill。

    Args:
        path: 文件路径。
        start_line: 起始行（1-based，可选）。
        end_line: 结束行（可选）。
    """

    def __init__(self, manifest: SkillManifest | None = None) -> None:
        super().__init__(manifest or FILE_READ_MANIFEST)

    async def execute(self, args: dict[str, Any]) -> SkillResult:
        path_str = args.get("path", "")
        if not path_str:
            return SkillResult(success=False, error="missing 'path' argument")

        path = Path(path_str)
        if not path.exists():
            return SkillResult(success=False, error=f"file not found: {path}")

        if not path.is_file():
            return SkillResult(success=False, error=f"not a file: {path}")

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()

            start = args.get("start_line", 1) - 1
            end = args.get("end_line", len(lines))
            selected = lines[start:end]

            # 加行号
            numbered = [
                f"{start + i + 1:>6}\t{line}"
                for i, line in enumerate(selected)
            ]
            output = "\n".join(numbered)

            logger.debug("file_read: %s (%d lines)", path, len(selected))
            return SkillResult(
                success=True,
                output=output,
                metadata={"lines": len(selected), "path": str(path)},
            )
        except Exception as e:
            return SkillResult(success=False, error=str(e))


class FileWriteSkill(Skill):
    """文件写入 Skill。

    Args:
        path: 文件路径。
        content: 写入内容。
        mode: 写入模式（``overwrite`` / ``append``）。
    """

    def __init__(self, manifest: SkillManifest | None = None) -> None:
        super().__init__(manifest or FILE_WRITE_MANIFEST)

    async def execute(self, args: dict[str, Any]) -> SkillResult:
        path_str = args.get("path", "")
        content = args.get("content", "")
        mode = args.get("mode", "overwrite")

        if not path_str:
            return SkillResult(success=False, error="missing 'path' argument")

        path = Path(path_str)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if mode == "append":
                with open(path, "a", encoding="utf-8") as f:
                    f.write(content)
            else:
                path.write_text(content, encoding="utf-8")

            logger.debug("file_write: %s (%d bytes, mode=%s)", path, len(content), mode)
            return SkillResult(
                success=True,
                output=f"wrote {len(content)} bytes to {path}",
                metadata={"bytes": len(content), "path": str(path), "mode": mode},
            )
        except Exception as e:
            return SkillResult(success=False, error=str(e))
