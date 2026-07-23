"""ChatGPT 站点适配器 — chatgpt.com。

ChatGPT 网页特征：
  - 输入框：contenteditable div（非 textarea）
  - 模式：下拉菜单选择（GPT-4o、Generate Image 等）
  - 响应：Markdown 渲染容器
  - 完成检测：停止按钮消失

当前使用通用实现，后续可根据 ChatGPT DOM 结构做站点特定优化。
"""

from __future__ import annotations

from multimind.adapters.sites.generic import GenericSiteAdapter

__all__ = ["ChatGPTSite"]


class ChatGPTSite(GenericSiteAdapter):
    """ChatGPT 站点适配器。

    继承通用适配器。ChatGPT 的输入框是 contenteditable div，
    可能在 ``send_prompt`` 中需要特殊处理（type 而非 fill）。
    后续迭代中覆盖 ``send_prompt`` 方法。
    """

    site_name = "chatgpt"
