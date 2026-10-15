"""Parse a prompt-mode model reply into a tool call, plain text or malformed output.

Models without native tool support are asked to reply with ONLY one JSON
object {"name": ..., "arguments": {...}} to call a tool, and plain text
otherwise. Small models wrap it in code fences or add prose, so this is
lenient about where the object sits but strict about its shape.

Pure: no I/O, standard library only.
"""

import json
import re
from dataclasses import dataclass

FENCE = re.compile(r"^```[\w-]*[ \t]*\n?(.*?)\n?```$", re.DOTALL)
# How far apart the tool name and a brace may be for an attempt to count.
NEAR_BRACE_CHARS = 20


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True)
class NoTool:
    pass


@dataclass(frozen=True)
class Malformed:
    reason: str


def strip_fence(text: str) -> str:
    """Remove one code fence that wraps the whole reply, if there is one."""
    text = text.strip()
    match = FENCE.match(text)
    return match.group(1).strip() if match else text


def json_objects(text: str) -> list[dict]:
    """Every top-level JSON object in the text, in order.

    After an object decodes, scanning resumes past its end, so the nested
    "arguments" object is not reported again.
    """
    decoder = json.JSONDecoder()
    objects = []
    position = text.find("{")
    while position != -1:
        try:
            value, end = decoder.raw_decode(text, position)
        except ValueError:
            position = text.find("{", position + 1)
            continue
        if isinstance(value, dict):
            objects.append(value)
        position = text.find("{", end)
    return objects


def is_call_shaped(value: dict) -> bool:
    return isinstance(value.get("name"), str) and isinstance(
        value.get("arguments"), dict
    )


def looks_like_attempt(text: str, tool_name: str) -> bool:
    """A reply starting with "{" (after any fence), or naming the tool next to a brace."""
    if strip_fence(text).startswith("{"):
        return True
    name = re.escape(tool_name)
    gap = f".{{0,{NEAR_BRACE_CHARS}}}"
    pattern = rf"[{{}}]{gap}{name}|{name}{gap}[{{}}]"
    return re.search(pattern, text, re.DOTALL) is not None


def describe_problem(objects: list[dict]) -> str:
    """Why the decoded objects are not one {"name": string, "arguments": object}."""
    if not objects:
        return "invalid JSON"
    value = objects[0]
    if "name" not in value:
        return "missing name"
    if not isinstance(value["name"], str):
        return "name is not a string"
    if "arguments" not in value:
        return "missing arguments"
    return "arguments is not an object"


def parse_reply(text: str, tool_name: str) -> ToolCall | NoTool | Malformed:
    """Classify a reply.

    A single well-formed call is a ToolCall even if its name is not tool_name;
    the caller's name check marks it invalid, as in native mode. Output that
    looks like an attempted call but has the wrong shape is Malformed. Anything
    else, including prose that happens to contain braces, is NoTool.
    """
    objects = json_objects(text)
    calls = [value for value in objects if is_call_shaped(value)]
    if len(calls) == 1:
        return ToolCall(calls[0]["name"], calls[0]["arguments"])
    if not looks_like_attempt(text, tool_name):
        return NoTool()
    if len(calls) > 1:
        return Malformed(f"{len(calls)} tool calls, expected one")
    return Malformed(describe_problem(objects))
