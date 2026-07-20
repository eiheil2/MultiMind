"""适配器工厂 — 根据通道类型创建适配器实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from multimind.adapters.api_client import APIClientAdapter
from multimind.adapters.browser import BrowserAdapter
from multimind.adapters.cli_reuse import CLIReuseAdapter
from multimind.adapters.local import LocalAdapter
from multimind.adapters.public_endpoint import PublicEndpointAdapter
from multimind.core.exceptions import AdapterError
from multimind.core.types import ChannelType, ProviderConfig

if TYPE_CHECKING:
    from multimind.core.interfaces import AIAdapter

__all__ = ["create_adapter"]

_ADAPTER_MAP: dict[ChannelType, type[AIAdapter]] = {
    ChannelType.CLI_REUSE: CLIReuseAdapter,
    ChannelType.API_CLIENT: APIClientAdapter,
    ChannelType.BROWSER: BrowserAdapter,
    ChannelType.PUBLIC_ENDPOINT: PublicEndpointAdapter,
    ChannelType.LOCAL: LocalAdapter,
}


def create_adapter(config: ProviderConfig, quota: object = None) -> AIAdapter:
    """根据通道类型创建适配器。

    Args:
        config: Provider 配置。
        quota: 可选的共享 QuotaTracker 实例；为 None 时适配器使用内存兜底。

    Returns:
        对应通道的适配器实例。

    Raises:
        AdapterError: 不支持的通道类型。
    """
    cls = _ADAPTER_MAP.get(config.channel)
    if cls is None:
        raise AdapterError(f"Unsupported channel type: {config.channel}")
    return cls(config, quota=quota)
