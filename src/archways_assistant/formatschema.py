"""Build the Ollama `format` schema for prompt mode from the search_announcements contract.

With --format-mode schema, Ollama constrains the reply to JSON matching this
schema: either a tool call {"name": "search_announcements", "arguments": ...}
or a plain answer {"reply": "..."}. The arguments schema is copied from the
contract, so the two can't drift apart.

Pure: no I/O, standard library only.
"""

import copy
import json

REPLY_KEY = "reply"


def build_format_schema(contract: dict) -> dict:
    """A schema allowing either a call to the contract's tool or a {"reply": string}."""
    call = {
        "type": "object",
        "properties": {
            "name": {"const": contract["title"]},
            "arguments": copy.deepcopy(contract["$defs"]["arguments"]),
        },
        "required": ["name", "arguments"],
        "additionalProperties": False,
    }
    reply = {
        "type": "object",
        "properties": {REPLY_KEY: {"type": "string"}},
        "required": [REPLY_KEY],
        "additionalProperties": False,
    }
    return {"anyOf": [call, reply]}


def unwrap_reply(text: str) -> str | None:
    """The answer text if the reply is exactly one {"reply": string} object, else None."""
    try:
        value = json.loads(text)
    except ValueError:
        return None
    if (
        isinstance(value, dict)
        and set(value) == {REPLY_KEY}
        and isinstance(value[REPLY_KEY], str)
    ):
        return value[REPLY_KEY]
    return None
