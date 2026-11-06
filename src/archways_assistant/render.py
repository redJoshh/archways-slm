"""Render chat messages into the exact prompt text Ollama feeds gemma3:1b.

render_gemma3() follows OLLAMA_TEMPLATE, the Go template printed by
`ollama show gemma3:1b --template` (Ollama 0.40.13), by hand:

- A system or user message becomes <start_of_turn>user, a newline, the
  content, then <end_of_turn> and a newline. So a system prompt is its own
  user turn, not merged into the next one.
- After the last message, if it is a system or user message, the model turn
  is opened: <start_of_turn>model and a newline.
- An assistant message becomes <start_of_turn>model, a newline and the
  content, closed with <end_of_turn> and a newline unless it is the last
  message.

Content is inserted as is (no trimming). The template drops other roles;
render_gemma3() rejects them instead, so a training example can't lose a
message silently. Whether Ollama adds a start-of-text token is decided by
the tokenizer, not the template; scripts/check_render.py measures it.

tests/test_render.py checks OLLAMA_TEMPLATE against the saved fixture, and
scripts/check_render.py checks it against the running Ollama.

render_qwen3() does the same for qwen3:0.6b. It follows QWEN3_OLLAMA_TEMPLATE,
the output of `ollama show qwen3:0.6b --template` (Ollama 0.40.14), as
/api/chat runs it with "think": false. It is a spec for the one shape the
pipeline sends, a system message then a user message, not an emulation of
the whole template:

- The system turn: <|im_start|>system, a newline, a blank line, the
  content, <|im_end|> and a newline. The blank line is printed by the
  template.
- The user turn: <|im_start|>user, a newline, the content, then " /no_think"
  (Ollama appends it to the last user message when thinking is off), then
  <|im_end|> and a newline.
- The open assistant turn: <|im_start|>assistant, a newline, and the empty
  think block <think>, a blank line, </think> and a blank line.

There is no start-of-text token, and content is inserted as is. Generation
stops at QWEN3_STOP. scripts/check_render_qwen3.py checks all of this
against the running Ollama.
"""

OLLAMA_TEMPLATE = '{{- range $i, $_ := .Messages }}\n{{- $last := eq (len (slice $.Messages $i)) 1 }}\n{{- if or (eq .Role "user") (eq .Role "system") }}<start_of_turn>user\n{{ .Content }}<end_of_turn>\n{{ if $last }}<start_of_turn>model\n{{ end }}\n{{- else if eq .Role "assistant" }}<start_of_turn>model\n{{ .Content }}{{ if not $last }}<end_of_turn>\n{{ end }}\n{{- end }}\n{{- end }}'

ROLES = {"system", "user", "assistant"}


def render_gemma3(messages: list[dict]) -> str:
    parts = []
    for index, message in enumerate(messages):
        role, content = message["role"], message["content"]
        if role not in ROLES:
            raise ValueError(f"unsupported role {role!r}")
        last = index == len(messages) - 1
        if role in ("system", "user"):
            parts.append(f"<start_of_turn>user\n{content}<end_of_turn>\n")
            if last:
                parts.append("<start_of_turn>model\n")
        else:
            parts.append(f"<start_of_turn>model\n{content}")
            if not last:
                parts.append("<end_of_turn>\n")
    return "".join(parts)


QWEN3_OLLAMA_TEMPLATE = '\n{{- $lastUserIdx := -1 -}}\n{{- range $idx, $msg := .Messages -}}\n{{- if eq $msg.Role "user" }}{{ $lastUserIdx = $idx }}{{ end -}}\n{{- end }}\n{{- if or .System .Tools }}<|im_start|>system\n{{ if .System }}\n{{ .System }}\n{{- end }}\n{{- if .Tools }}\n\n# Tools\n\nYou may call one or more functions to assist with the user query.\n\nYou are provided with function signatures within <tools></tools> XML tags:\n<tools>\n{{- range .Tools }}\n{"type": "function", "function": {{ .Function }}}\n{{- end }}\n</tools>\n\nFor each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n<tool_call>\n{"name": <function-name>, "arguments": <args-json-object>}\n</tool_call>\n{{- end -}}\n<|im_end|>\n{{ end }}\n{{- range $i, $_ := .Messages }}\n{{- $last := eq (len (slice $.Messages $i)) 1 -}}\n{{- if eq .Role "user" }}<|im_start|>user\n{{ .Content }}\n{{- if and $.IsThinkSet (eq $i $lastUserIdx) }}\n   {{- if $.Think -}}\n      {{- " "}}/think\n   {{- else -}}\n      {{- " "}}/no_think\n   {{- end -}}\n{{- end }}<|im_end|>\n{{ else if eq .Role "assistant" }}<|im_start|>assistant\n{{ if (and $.IsThinkSet (and .Thinking (or $last (gt $i $lastUserIdx)))) -}}\n<think>{{ .Thinking }}</think>\n{{ end -}}\n{{ if .Content }}{{ .Content }}\n{{- else if .ToolCalls }}<tool_call>\n{{ range .ToolCalls }}{"name": "{{ .Function.Name }}", "arguments": {{ .Function.Arguments }}}\n{{ end }}</tool_call>\n{{- end }}{{ if not $last }}<|im_end|>\n{{ end }}\n{{- else if eq .Role "tool" }}<|im_start|>user\n<tool_response>\n{{ .Content }}\n</tool_response><|im_end|>\n{{ end }}\n{{- if and (ne .Role "assistant") $last }}<|im_start|>assistant\n{{ if and $.IsThinkSet (not $.Think) -}}\n<think>\n\n</think>\n\n{{ end -}}\n{{ end }}\n{{- end }}'


# From `ollama show qwen3:0.6b --parameters`.
QWEN3_STOP = ("<|im_end|>", "<|im_start|>")
QWEN3_NO_THINK = " /no_think"
QWEN3_EMPTY_THINK = "<think>\n\n</think>\n\n"


def render_qwen3(messages: list[dict]) -> str:
    """The prompt text Ollama feeds qwen3:0.6b for [system, user], thinking off.

    Any other shape raises ValueError, so an unverified rendering can't be
    used silently. An empty system message is rejected because the template
    would drop the system turn.
    """
    roles = [message.get("role") for message in messages]
    if roles != ["system", "user"]:
        raise ValueError(f"expected roles ['system', 'user'], got {roles!r}")
    system, user = messages[0]["content"], messages[1]["content"]
    if not system:
        raise ValueError("empty system message")
    return (
        f"<|im_start|>system\n\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{user}{QWEN3_NO_THINK}<|im_end|>\n"
        f"<|im_start|>assistant\n{QWEN3_EMPTY_THINK}"
    )


def render_qwen3_example(messages: list[dict], reply: str) -> tuple[str, str]:
    """A training example: (prompt, target), where loss is on target only.

    prompt is render_qwen3(messages), exactly what the model sees at
    inference, including " /no_think" and the empty think block. target is
    the reply followed by <|im_end|>, exactly what the model emits with
    thinking off.

    This is not Ollama's rendering of [system, user, assistant]. That would
    leave out the empty think block (the template prints a think block for
    a history message only if it has thinking text), which the model does
    see before its reply at inference.
    """
    if not reply:
        raise ValueError("empty reply")
    for marker in (*QWEN3_STOP, "<think>", "</think>"):
        if marker in reply:
            raise ValueError(f"reply contains {marker!r}")
    return render_qwen3(messages), f"{reply}<|im_end|>"
