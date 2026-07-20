"""KIMI 站点适配器 — kimi.com。

KIMI 网页特征：
  - 输入框：底部文本框
  - 模式：PPT 模板选择（专业化场景）
  - 响应：Markdown 渲染容器
  - 完成检测：停止按钮消失

当前使用通用实现，后续可根据 KIMI DOM 结构做站点特定优化。
"""

from __future__ import annotations

from multimind.adapters.sites.generic import GenericSiteAdapter

__all__ = ["KimiSite"]


class KimiSite(GenericSiteAdapter):
    """KIMI 站点适配器。

    继承通用适配器。KIMI 的 PPT 生成可能需要特殊的多步流程
    （选择模板 → 输入主题 → 等待生成 → 下载）。
    后续迭代中覆盖 ``send_prompt`` 和 ``wait_for_complete`` 方法。
    """

    site_name = "kimi"
