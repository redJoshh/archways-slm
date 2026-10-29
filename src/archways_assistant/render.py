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
