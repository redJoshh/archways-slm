import pytest

from archways_assistant.toolparse import Malformed, NoTool, ToolCall, parse_reply

NAME = "search_announcements"
CALL = '{"name": "search_announcements", "arguments": {"query": "registrar"}}'
EXPECTED = ToolCall(NAME, {"query": "registrar"})


def parse(text: str):
    return parse_reply(text, NAME)


def test_bare_json():
    assert parse(CALL) == EXPECTED


def test_bare_json_with_surrounding_whitespace():
    assert parse(f"\n  {CALL}  \n") == EXPECTED


@pytest.mark.parametrize("opening", ["```json", "```", "```JSON"])
def test_json_in_code_fence(opening):
    assert parse(f"{opening}\n{CALL}\n```") == EXPECTED


def test_prose_before_json():
    assert parse(f"Let me search for that.\n{CALL}") == EXPECTED


def test_prose_after_json():
    assert parse(f"{CALL}\nI will look this up.") == EXPECTED


def test_prose_around_fenced_json():
    assert parse(f"Sure!\n```json\n{CALL}\n```\nOne moment.") == EXPECTED


def test_nested_arguments_are_not_a_second_object():
    text = '{"name": "search_announcements", "arguments": {"query": "library", "days": 7, "limit": 3}}'
    assert parse(text) == ToolCall(NAME, {"query": "library", "days": 7, "limit": 3})


def test_empty_arguments_object_is_a_call():
    text = '{"name": "search_announcements", "arguments": {}}'
    assert parse(text) == ToolCall(NAME, {})


@pytest.mark.parametrize(
    "text",
    [
        "15 times 12 is 180.",
        "Hi! I'm the UST Archways assistant.",
        "",
        "   ",
        "I can call search_announcements if you ask about announcements.",
    ],
)
def test_plain_text_is_no_tool(text):
    assert parse(text) == NoTool()


@pytest.mark.parametrize(
    "text",
    [
        "Dear {name}, roses are red.",
        "A poem in code:\n    if (love) { return forever; }\nThe end.",
        'Roses are red,\nhere is some JSON: {"color": "red"}\nand so are you.',
    ],
)
def test_prose_with_braces_is_no_tool(text):
    assert parse(text) == NoTool()


@pytest.mark.parametrize(
    "text",
    [
        '{"name": "search_announcements", "arguments": {"query": "regis',
        "{'name': 'search_announcements', 'arguments': {'query': 'x'}}",
        '```json\n{"name": "search_announcements", "arguments": {"query": }}\n```',
        'Calling search_announcements({"query": "library"',
    ],
)
def test_malformed_json(text):
    assert parse(text) == Malformed("invalid JSON")


def test_wrong_function_name_is_a_tool_call():
    text = '{"name": "get_weather", "arguments": {"city": "Manila"}}'
    assert parse(text) == ToolCall("get_weather", {"city": "Manila"})


@pytest.mark.parametrize("arguments", ['"registrar"', '["registrar"]', "null", "7"])
def test_arguments_not_an_object(arguments):
    text = f'{{"name": "search_announcements", "arguments": {arguments}}}'
    assert parse(text) == Malformed("arguments is not an object")


def test_arguments_as_json_string_is_malformed():
    text = '{"name": "search_announcements", "arguments": "{\\"query\\": \\"x\\"}"}'
    assert parse(text) == Malformed("arguments is not an object")


def test_missing_arguments():
    text = '{"name": "search_announcements", "query": "registrar"}'
    assert parse(text) == Malformed("missing arguments")


def test_missing_name():
    assert parse('{"query": "registrar"}') == Malformed("missing name")


def test_name_not_a_string():
    text = '{"name": 1, "arguments": {"query": "registrar"}}'
    assert parse(text) == Malformed("name is not a string")


def test_two_calls_is_malformed():
    assert parse(f"{CALL}\n{CALL}") == Malformed("2 tool calls, expected one")


def test_tool_name_next_to_brace_in_prose_is_an_attempt():
    text = 'I will run search_announcements {query: "registrar"} now.'
    assert parse(text) == Malformed("invalid JSON")
