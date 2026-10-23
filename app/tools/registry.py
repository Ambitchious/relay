"""Tool registry.

A tool is a plain Python callable plus a JSON Schema describing its arguments.
The registry hands the schemas to the model and dispatches by name when the
model asks for one. Keeping dispatch here — rather than in the agent loop —
means adding a tool is one decorator and no change to the loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self, name: str, description: str, parameters: dict[str, Any]
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._tools[name] = Tool(name, description, parameters, fn)
            return fn

        return decorator

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def dispatch(self, name: str, arguments: dict[str, Any]) -> str:
        """Run a tool and return a string for the model.

        Errors are returned as text rather than raised. A tool that blows up
        should give the model a chance to recover — pick a different tool, or
        tell the user it cannot answer — instead of killing the whole request.
        """
        tool = self._tools.get(name)
        if tool is None:
            return (
                f"Error: no tool named {name!r}. "
                f"Available tools: {', '.join(self.names())}."
            )
        try:
            return str(tool.fn(**arguments))
        except TypeError as exc:
            return f"Error: wrong arguments for {name!r} ({exc})."
        except Exception as exc:  # noqa: BLE001 - surfaced to the model on purpose
            return f"Error: {name!r} failed ({type(exc).__name__}: {exc})."


registry = ToolRegistry()
