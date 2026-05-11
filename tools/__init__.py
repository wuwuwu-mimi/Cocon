from .registry import ToolRegistry
from .builtin import BUILTIN_TOOLS_MANIFEST

registry = ToolRegistry()

for tool in BUILTIN_TOOLS_MANIFEST:
    registry.register(
        name=tool["name"],
        func=tool["func"],
        schema=tool["schema"]
    )

__all__ = ["registry"]