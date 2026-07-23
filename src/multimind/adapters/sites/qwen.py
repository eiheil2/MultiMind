"""通义千问站点适配器 — qwen.ai。

通义千问网页特征：
  - 输入框：底部文本框
  - 模式：6 个功能标签（图片编辑、深度思考、联网搜索、
    网页开发、图片生成、视频生成）
  - 响应：Markdown 渲染容器
  - 完成检测：停止按钮消失

当前使用通用实现，后续可根据千问 DOM 结构做站点特定优化。
"""

from __future__ import annotations

from multimind.adapters.sites.generic import GenericSiteAdapter

__all__ = ["QwenSite"]


class QwenSite(GenericSiteAdapter):
    """通义千问站点适配器。

    继承通用适配器。千问的 6 个功能标签可能需要特殊的多步选择逻辑。
    后续迭代中覆盖 ``select_mode`` 方法。
    """

    site_name = "qwen"
