"""Tool package.

Importing this package registers every tool as a side effect, so the agent can
depend on `app.tools.registry.registry` being populated without knowing which
tool modules exist.
"""

from app.tools.registry import Tool, ToolRegistry, registry

# Side-effect imports: each module registers its tool on import.
from app.tools import incidents, metrics, runbooks  # noqa: E402,F401

__all__ = ["Tool", "ToolRegistry", "registry", "incidents", "metrics", "runbooks"]
