"""Read saved end-to-end probe runs (runs/*.txt) back into per-case records.

runs/ is gitignored, so this only works on a machine that has the files.

What a run file keeps, and what it loses:
- Files are UTF-8 or, when the probe's stdout was redirected on Windows,
  cp1252. A file that isn't valid UTF-8 is read as cp1252. The probe would
  have crashed on a character cp1252 can't encode, so this is lossless.
- The probe printed each reply on one line with "\\n" replaced by " | "
  and cut to REPLY_PREVIEW_CHARS (400); no saved reply reaches 400.
  restored_reply() turns " | " back into "\\n", which is wrong if the
  model itself wrote " | ".
- Results are logged as ids only; rebuild them from the seed rows.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

HEADER = re.compile(
    r"^model=(?P<model>\S+) .*?\bcases=(?P<cases>\S+) .*?\bnow=(?P<now>\S+)"
)
CASE = re.compile(r"^\[(?P<n>\d+)/(?P<total>\d+)\] (?P<id>\S+): (?P<question>.*)$")
SEARCH = re.compile(r"^  search: (?P<count>\d+) result\(s\) (?P<ids>\[.*?\])")


@dataclass
class RunCase:
    path: Path
    model: str
    cases_file: str
    case_id: str
    question: str
    ids: list[str]
    answered: bool
    reply: str | None = None
    guard_line: str | None = None
    final: str | None = None


def read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def is_probe_run(path: Path) -> bool:
    """An end-to-end probe run: e2e or Taglish, with a header line."""
    if not path.name.startswith(("e2e", "taglish")):
        return False
    first = read_text(path).split("\n", 1)[0]
    return bool(HEADER.match(first))


def parse(path: Path) -> list[RunCase]:
    lines = read_text(path).splitlines()
    header = HEADER.match(lines[0])
    if not header:
        raise ValueError(f"{path}: no probe header")
    records: list[RunCase] = []
    current: RunCase | None = None
    for line in lines[1:]:
        if match := CASE.match(line):
            current = RunCase(
                path=path,
                model=header["model"],
                cases_file=header["cases"],
                case_id=match["id"],
                question=match["question"],
                ids=[],
                answered=False,
            )
            records.append(current)
        elif current is None:
            continue
        elif match := SEARCH.match(line):
            current.ids = ast.literal_eval(match["ids"])
        elif line.startswith("  answer: prompt tokens"):
            current.answered = True
        elif line.startswith("  reply: "):
            current.reply = line[len("  reply: ") :]
        elif line.startswith("  guard: "):
            current.guard_line = line[len("  guard: ") :]
        elif line.startswith("  final: "):
            current.final = line[len("  final: ") :]
    return records


def restored_reply(logged: str) -> str:
    """The logged reply with the probe's " | " line joins turned back into "\\n"."""
    return logged.replace(" | ", "\n")
