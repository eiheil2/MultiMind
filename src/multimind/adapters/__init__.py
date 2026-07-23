"""AI 适配器层 — 五类通道的具体实现。

每个通道实现 ``AIAdapter`` 接口，通过 ``registry`` 统一注册和路由。
新增 AI 只需写一个适配器文件并在 registry 注册。
"""

from multimind.adapters.api_client import APIClientAdapter
from multimind.adapters.base import create_adapter
from multimind.adapters.browser import BrowserAdapter
from multimind.adapters.cli_reuse import CLIReuseAdapter
from multimind.adapters.local import LocalAdapter
from multimind.adapters.public_endpoint import PublicEndpointAdapter
from multimind.adapters.registry import ProviderRegistry, get_registry, init_default_providers

__all__ = [
    "create_adapter",
    "ProviderRegistry",
    "get_registry",
    "init_default_providers",
    "CLIReuseAdapter",
    "APIClientAdapter",
    "BrowserAdapter",
    "PublicEndpointAdapter",
    "LocalAdapter",
]
