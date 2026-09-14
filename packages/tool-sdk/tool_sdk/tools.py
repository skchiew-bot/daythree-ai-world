"""Tool implementations. Each tool is a plain callable: `(params, context) -> result`.

`artifact.write` / `artifact.read` don't perform I/O themselves — they delegate to
whatever `ArtifactPort` the caller (the agent runtime) injects into `ToolContext`, so
this package never has to import the artifact service's storage internals (spec §4
rule 7/8: runtime/storage stay swappable behind an interface).
"""
from __future__ import annotations

import ast
import operator
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


class ArtifactPort(Protocol):
    async def read(self, artifact_id: str) -> dict[str, Any]: ...
    async def write(self, title: str, content: str, mime_type: str) -> dict[str, Any]: ...


@dataclass
class ToolContext:
    available_context: dict[str, Any] = field(default_factory=dict)
    artifact_port: ArtifactPort | None = None


_SAFE_OPERATORS: dict[type, Callable[..., float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> float:
    """A restricted arithmetic evaluator — numbers and + - * / ** only, no names, no
    calls, no attribute access. This is what makes `calculator.execute` safe to expose
    to a model without becoming an arbitrary-code-execution tool in disguise.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPERATORS:
        return _SAFE_OPERATORS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPERATORS:
        return _SAFE_OPERATORS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression element: {ast.dump(node)}")


def calculator_execute(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    expression = params.get("expression", "")
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree.body)
    except Exception as exc:  # noqa: BLE001 — deliberately converted to a typed tool error
        raise ValueError(f"calculator.execute could not evaluate '{expression}': {exc}") from exc
    return {"expression": expression, "result": result}


def knowledge_read(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Phase 0 has no external knowledge base — "no open internet scraping" (spec §12).
    This reads only from the context the Mission Engine explicitly assembled and handed
    to the run (`available_context`), never anything fetched live.
    """
    key = params.get("key")
    if key is None or key not in context.available_context:
        return {"key": key, "found": False, "value": None}
    return {"key": key, "found": True, "value": context.available_context[key]}


async def artifact_read(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    if context.artifact_port is None:
        raise RuntimeError("artifact.read tool was invoked without an ArtifactPort bound.")
    return await context.artifact_port.read(params["artifact_id"])


async def artifact_write(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    if context.artifact_port is None:
        raise RuntimeError("artifact.write tool was invoked without an ArtifactPort bound.")
    return await context.artifact_port.write(
        title=params["title"], content=params["content"], mime_type=params.get("mime_type", "text/plain")
    )


ToolHandler = Callable[[dict[str, Any], ToolContext], Any]

DEFAULT_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "calculator.execute": calculator_execute,
    "knowledge.read": knowledge_read,
    "artifact.read": artifact_read,
    "artifact.write": artifact_write,
}
