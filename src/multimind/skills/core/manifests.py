"""核心 Skill 清单（skill.toml）定义。

内置核心 skill 的清单不使用外部文件，而是代码内定义。
"""

from __future__ import annotations

from multimind.core.types import Permission
from multimind.skills.base import SkillManifest, SourceType

__all__ = [
    "FILE_READ_MANIFEST",
    "FILE_WRITE_MANIFEST",
    "HTTP_REQUEST_MANIFEST",
    "SHELL_EXEC_MANIFEST",
    "CODE_SEARCH_MANIFEST",
]

# ── 核心自研 skill 清单 ──────────────────────────────────────────

FILE_READ_MANIFEST = SkillManifest(
    name="file_read",
    version="0.1.0",
    description="读取文件内容，支持行范围和编码探测",
    entry_point="multimind.skills.core.file_ops:FileReadSkill",
    source_type=SourceType.CORE,
    license="Apache-2.0",
    tags=("file", "io", "read"),
    requires_sandbox=False,
    requires_permission=Permission.AUTO,
)

FILE_WRITE_MANIFEST = SkillManifest(
    name="file_write",
    version="0.1.0",
    description="写入文件，支持覆盖、追加、SearchReplace 模式",
    entry_point="multimind.skills.core.file_ops:FileWriteSkill",
    source_type=SourceType.CORE,
    license="Apache-2.0",
    tags=("file", "io", "write"),
    requires_sandbox=False,
    requires_permission=Permission.ASK,
)

HTTP_REQUEST_MANIFEST = SkillManifest(
    name="http_request",
    version="0.1.0",
    description="HTTP 请求，支持 GET/POST/PUT/DELETE 和流式响应",
    entry_point="multimind.skills.core.http:HttpRequestSkill",
    source_type=SourceType.CORE,
    license="Apache-2.0",
    tags=("http", "network", "api"),
    requires_sandbox=False,
    requires_permission=Permission.AUTO,
)

SHELL_EXEC_MANIFEST = SkillManifest(
    name="shell_exec",
    version="0.1.0",
    description="Shell 命令执行，沙箱内运行，超时控制",
    entry_point="multimind.skills.core.shell:ShellExecSkill",
    source_type=SourceType.CORE,
    license="Apache-2.0",
    tags=("shell", "exec", "sandbox"),
    requires_sandbox=True,
    requires_permission=Permission.ASK,
)

CODE_SEARCH_MANIFEST = SkillManifest(
    name="code_search",
    version="0.1.0",
    description="代码库搜索，支持 grep/glob/语义搜索",
    entry_point="multimind.skills.core.search:CodeSearchSkill",
    source_type=SourceType.CORE,
    license="Apache-2.0",
    tags=("search", "code", "grep"),
    requires_sandbox=False,
    requires_permission=Permission.AUTO,
)
