"""豆包站点适配器 — doubao.com。

豆包网页特征：
  - 输入框：底部圆角文本框
  - 模式：快问快答切换
  - 响应：消息内容容器
  - 完成检测：停止按钮消失

当前使用通用实现，后续可根据豆包 DOM 结构做站点特定优化。
"""

from __future__ import annotations

from multimind.adapters.sites.generic import GenericSiteAdapter

__all__ = ["DoubaoSite"]


class DoubaoSite(GenericSiteAdapter):
    """豆包站点适配器。

    继承通用适配器。豆包的快问快答模式切换可能需要特殊处理。
    后续迭代中覆盖 ``select_mode`` 方法。
    """

    site_name = "doubao"
