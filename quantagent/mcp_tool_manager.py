from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Union, get_args, get_origin


# Ported from Anthropic MCP Python SDK (MIT):
# - mcp/server/mcpserver/tools/base.py
# - mcp/server/mcpserver/tools/tool_manager.py
# - mcp/shared/tool_name_validation.py
#
# This module keeps the useful MCP Tool/ToolManager shape but avoids depending
# on pydantic internals so OpenMako can expose a stable native tool layer.

logger = logging.getLogger(__name__)

TOOL_NAME_REGEX = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SEP_986_URL = "https://modelcontextprotocol.io/specification/2025-11-25/server/tools#tool-names"


class MakoToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolNameValidationResult:
    is_valid: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MakoMcpTool:
    fn: Callable[..., Any]
    name: str
    description: str
    parameters: dict[str, Any]
    title: str | None = None
    is_async: bool = False
    context_kwarg: str | None = None
    annotations: dict[str, Any] | None = None
    icons: list[dict[str, Any]] | None = None
    meta: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        context_kwarg: str | None = None,
        annotations: dict[str, Any] | None = None,
        icons: list[dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> "MakoMcpTool":
        func_name = name or getattr(fn, "__name__", "")
        validate_and_warn_tool_name(func_name)
        if func_name == "<lambda>" or not func_name:
            raise ValueError("You must provide a name for lambda functions")
        if context_kwarg is None:
            context_kwarg = find_context_parameter(fn)
        return cls(
            fn=fn,
            name=func_name,
            title=title,
            description=(description if description is not None else inspect.getdoc(fn) or ""),
            parameters=function_parameters_schema(fn, skip_names=[context_kwarg] if context_kwarg else []),
            is_async=inspect.iscoroutinefunction(fn),
            context_kwarg=context_kwarg,
            annotations=annotations,
            icons=icons,
            meta=meta,
            output_schema=annotation_to_schema(inspect.signature(fn).return_annotation),
        )

    async def run(self, arguments: dict[str, Any] | None = None, *, context: Any = None) -> Any:
        arguments = dict(arguments or {})
        kwargs = validate_arguments(self.parameters, arguments)
        if self.context_kwarg is not None:
            kwargs[self.context_kwarg] = context
        try:
            result = self.fn(**kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        except Exception as exc:
            raise MakoToolError(f"Error executing tool {self.name}: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.parameters,
            "outputSchema": self.output_schema,
            "annotations": self.annotations,
            "icons": self.icons,
            "meta": self.meta,
        }


class MakoMcpToolManager:
    def __init__(self, warn_on_duplicate_tools: bool = True, *, tools: list[MakoMcpTool] | None = None) -> None:
        self._tools: dict[str, MakoMcpTool] = {}
        self.warn_on_duplicate_tools = warn_on_duplicate_tools
        for tool in tools or ():
            if warn_on_duplicate_tools and tool.name in self._tools:
                logger.warning("Tool already exists: %s", tool.name)
            self._tools[tool.name] = tool

    def get_tool(self, name: str) -> MakoMcpTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[MakoMcpTool]:
        return list(self._tools.values())

    def add_tool(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: dict[str, Any] | None = None,
        icons: list[dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> MakoMcpTool:
        tool = MakoMcpTool.from_function(
            fn,
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            icons=icons,
            meta=meta,
        )
        existing = self._tools.get(tool.name)
        if existing:
            if self.warn_on_duplicate_tools:
                logger.warning("Tool already exists: %s", tool.name)
            return existing
        self._tools[tool.name] = tool
        return tool

    def remove_tool(self, name: str) -> None:
        if name not in self._tools:
            raise MakoToolError(f"Unknown tool: {name}")
        del self._tools[name]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None, *, context: Any = None) -> Any:
        tool = self.get_tool(name)
        if not tool:
            raise MakoToolError(f"Unknown tool: {name}")
        return await tool.run(arguments or {}, context=context)


def validate_tool_name(name: str) -> ToolNameValidationResult:
    warnings: list[str] = []
    if not name:
        return ToolNameValidationResult(False, ["Tool name cannot be empty"])
    if len(name) > 128:
        return ToolNameValidationResult(False, [f"Tool name exceeds maximum length of 128 characters (current: {len(name)})"])
    if " " in name:
        warnings.append("Tool name contains spaces, which may cause parsing issues")
    if "," in name:
        warnings.append("Tool name contains commas, which may cause parsing issues")
    if name.startswith("-") or name.endswith("-"):
        warnings.append("Tool name starts or ends with a dash, which may cause parsing issues in some contexts")
    if name.startswith(".") or name.endswith("."):
        warnings.append("Tool name starts or ends with a dot, which may cause parsing issues in some contexts")
    if not TOOL_NAME_REGEX.fullmatch(name):
        invalid_chars: list[str] = []
        seen: set[str] = set()
        for char in name:
            if not re.fullmatch(r"[A-Za-z0-9._-]", char) and char not in seen:
                invalid_chars.append(char)
                seen.add(char)
        warnings.append(f"Tool name contains invalid characters: {', '.join(repr(char) for char in invalid_chars)}")
        warnings.append("Allowed characters are: A-Z, a-z, 0-9, underscore (_), dash (-), and dot (.)")
        return ToolNameValidationResult(False, warnings)
    return ToolNameValidationResult(True, warnings)


def issue_tool_name_warning(name: str, warnings: list[str]) -> None:
    if not warnings:
        return
    logger.warning('Tool name validation warning for "%s":', name)
    for warning in warnings:
        logger.warning("  - %s", warning)
    logger.warning("Tool registration will proceed, but this may cause compatibility issues.")
    logger.warning("Consider updating the tool name to conform to the MCP tool naming standard.")
    logger.warning("See SEP-986 (%s) for more details.", SEP_986_URL)


def validate_and_warn_tool_name(name: str) -> bool:
    result = validate_tool_name(name)
    issue_tool_name_warning(name, result.warnings)
    return result.is_valid


def find_context_parameter(fn: Callable[..., Any]) -> str | None:
    signature = inspect.signature(fn)
    for name, parameter in signature.parameters.items():
        annotation = parameter.annotation
        annotation_name = getattr(annotation, "__name__", str(annotation)).lower()
        if name in {"ctx", "context"} or annotation_name.endswith("context"):
            return name
    return None


def function_parameters_schema(fn: Callable[..., Any], *, skip_names: list[str] | None = None) -> dict[str, Any]:
    skip = set(skip_names or [])
    signature = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in signature.parameters.items():
        if name in skip:
            continue
        if parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue
        schema = annotation_to_schema(parameter.annotation) or {}
        if parameter.default is not inspect._empty:
            schema = schema | {"default": parameter.default}
        else:
            required.append(name)
        properties[name] = schema
    payload: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        payload["required"] = required
    return payload


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = set(schema.get("required") or [])
    missing = sorted(name for name in required if name not in arguments)
    if missing:
        raise MakoToolError(f"Missing required tool argument(s): {', '.join(missing)}")
    unknown = sorted(name for name in arguments if name not in properties)
    if unknown and schema.get("additionalProperties") is False:
        raise MakoToolError(f"Unknown tool argument(s): {', '.join(unknown)}")
    out: dict[str, Any] = {}
    for name, spec in properties.items():
        if name in arguments:
            out[name] = _coerce_argument(name, arguments[name], spec)
        elif isinstance(spec, dict) and "default" in spec:
            out[name] = spec["default"]
    return out


def annotation_to_schema(annotation: Any) -> dict[str, Any] | None:
    if annotation is inspect._empty:
        return {}
    if isinstance(annotation, str):
        return _simple_type_schema(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is None:
        return _simple_type_schema(annotation)
    if origin in {list, tuple, set}:
        item_schema = annotation_to_schema(args[0]) if args else {}
        return {"type": "array", "items": item_schema or {}}
    if origin is dict:
        return {"type": "object"}
    if origin is Union:
        schemas = [annotation_to_schema(arg) or {} for arg in args]
        return {"anyOf": schemas}
    return {}


def _simple_type_schema(annotation: Any) -> dict[str, Any]:
    if annotation in {str, "str"}:
        return {"type": "string"}
    if annotation in {int, "int"}:
        return {"type": "integer"}
    if annotation in {float, "float"}:
        return {"type": "number"}
    if annotation in {bool, "bool"}:
        return {"type": "boolean"}
    if annotation in {dict, "dict"}:
        return {"type": "object"}
    if annotation in {list, tuple, set, "list", "tuple", "set"}:
        return {"type": "array", "items": {}}
    if annotation in {type(None), "None"}:
        return {"type": "null"}
    if annotation in {Any, "Any"}:
        return {}
    return {}


def _coerce_argument(name: str, value: Any, spec: Any) -> Any:
    if not isinstance(spec, dict):
        return value
    expected = spec.get("type")
    if expected == "string" and not isinstance(value, str):
        raise MakoToolError(f"Tool argument {name!r} must be a string")
    if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise MakoToolError(f"Tool argument {name!r} must be an integer")
    if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise MakoToolError(f"Tool argument {name!r} must be a number")
    if expected == "boolean" and not isinstance(value, bool):
        raise MakoToolError(f"Tool argument {name!r} must be a boolean")
    if expected == "array" and not isinstance(value, list):
        raise MakoToolError(f"Tool argument {name!r} must be an array")
    if expected == "object" and not isinstance(value, dict):
        raise MakoToolError(f"Tool argument {name!r} must be an object")
    return value
