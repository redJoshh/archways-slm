"""Generate the Ollama tool definition from the search_announcements contract."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts" / "search_announcements.schema.json"
OUTPUT_PATH = ROOT / "generated" / "search_announcements.tool.json"

# Keywords dropped without a sentence: they are not meant for the model.
SILENT_KEYWORDS = {"$comment"}
# Keywords folded into the description by describe_constraints().
FOLDED_KEYWORDS = {
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "default",
}
PROPERTY_KEYWORDS = {"type", "description"} | SILENT_KEYWORDS | FOLDED_KEYWORDS
ARGUMENTS_KEYWORDS = {"type", "properties", "required", "additionalProperties"}
ARGUMENTS_KEYWORDS |= SILENT_KEYWORDS

PATTERNS = {"\\S": "Must contain at least one non-whitespace character."}
FORMATS = {"date-time": "ISO 8601 date-time with a UTC offset."}


def check_keywords(node: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(node) - allowed)
    if unknown:
        raise ValueError(f"{where}: no rendering rule for {', '.join(unknown)}")


def sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith(".") else f"{text}."


def describe_constraints(prop: dict, where: str) -> list[str]:
    sentences = []
    noun = "Whole number" if prop.get("type") == "integer" else "Number"
    low, high = prop.get("minimum"), prop.get("maximum")
    if low is not None and high is not None:
        sentences.append(f"{noun} from {low} to {high}.")
    elif low is not None:
        sentences.append(f"{noun}, at least {low}.")
    elif high is not None:
        sentences.append(f"{noun}, at most {high}.")

    if "minLength" in prop:
        n = prop["minLength"]
        sentences.append(
            "Must not be empty." if n == 1 else f"At least {n} characters."
        )
    if "maxLength" in prop:
        sentences.append(f"At most {prop['maxLength']} characters.")

    if "pattern" in prop:
        if prop["pattern"] not in PATTERNS:
            raise ValueError(
                f"{where}: no rendering rule for pattern {prop['pattern']!r}"
            )
        sentences.append(PATTERNS[prop["pattern"]])
    if "format" in prop:
        if prop["format"] not in FORMATS:
            raise ValueError(
                f"{where}: no rendering rule for format {prop['format']!r}"
            )
        sentences.append(FORMATS[prop["format"]])

    if "default" in prop:
        sentences.append(f"Default {json.dumps(prop['default'])}.")
    return sentences


def build_property(name: str, prop: dict) -> dict:
    where = f"arguments.{name}"
    check_keywords(prop, PROPERTY_KEYWORDS, where)
    parts = [sentence(prop["description"])] if "description" in prop else []
    parts += describe_constraints(prop, where)
    return {"type": prop["type"], "description": " ".join(parts)}


def build_tool_definition(schema: dict) -> dict:
    arguments = schema["$defs"]["arguments"]
    check_keywords(arguments, ARGUMENTS_KEYWORDS, "arguments")
    properties = {
        name: build_property(name, prop)
        for name, prop in arguments["properties"].items()
    }
    return {
        "type": "function",
        "function": {
            "name": schema["title"],
            "description": schema["description"],
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(arguments.get("required", [])),
            },
        },
    }


def render(tool: dict) -> str:
    return json.dumps(tool, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(
        render(build_tool_definition(schema)), encoding="utf-8", newline="\n"
    )
    print(f"Wrote {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
