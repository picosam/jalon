"""park: file a scoped issue, reject a deposit, record a closed decision.

`gh` does the filing; GitHub holds the closing. What is ours is the bar an issue passes
before it is filed, and the record a closed decision leaves in `decisions/`.
"""

from __future__ import annotations

import contextlib
import datetime
import fcntl
import json
import os
import re
import subprocess
from pathlib import Path

from . import leak
from .leak import Refused

SECTIONS = ("Why", "Done when", "Out of scope", "Rulings it touches", "Waits on",
            "Evidence", "Assumptions", "Related items")
DEPTHS = ("none", "quick", "full")
HEADING = re.compile(r" {0,3}## (.*)")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
LIST_ITEM = re.compile(r" {0,3}([-*+]|\d{1,9}[.)])\s+\S")
RULING = re.compile(r'(?P<date>\d{4}-\d{2}-\d{2})\b.*?(?:\b(?P<hour>\d{1,2}):(?P<minute>\d{2})\b|time unknown).*?"[^"]+"')
# The new-code line: "none", or its parts in this order, with the author's
# own words between them (the scope skill gives a template, and issues word
# their parts freely).
NEW_CODE = re.compile(r"New code: (none\b.*|\S.*?\babout (\d{1,3}(,\d{3})+|\d+) lines\b.*?\blooked at\s+\S.*?"
                      r"\bdo less\b\W*\w.*)")


def _gh(*args: str, input: str | None = None, env: dict[str, str] | None = None) -> str:
    try:
        run = subprocess.run(["gh", *args], input=input, capture_output=True, text=True, env=env)
    except FileNotFoundError:
        raise Refused("gh is not installed") from None
    if run.returncode != 0:
        raise Refused(f"gh {' '.join(args[:2])}: {run.stderr.strip() or run.stdout.strip()}")
    return run.stdout


def _sections(text: str) -> list[tuple[str, list[tuple[str, bool]]]]:
    """The `## ` sections of a markdown text, in order. Each line comes with
    whether it is code: a fenced line is content, but never a heading or a
    list item. A fence closes on a run of its own character at least as long
    as the one that opened it."""
    found: list[tuple[str, list[tuple[str, bool]]]] = []
    fence = ""
    for line in text.splitlines():
        if fence:
            run = FENCE.match(line)
            if run and line.strip() == run.group(1) and run.group(1).startswith(fence):
                fence = ""
            if found:
                found[-1][1].append((line, True))
            continue
        if run := FENCE.match(line):
            fence = run.group(1)
            if found:
                found[-1][1].append((line, True))
        elif heading := HEADING.match(line):
            found.append((heading.group(1).strip(), []))
        elif found:
            found[-1][1].append((line, False))
    return found


def _paragraph(lines: list[tuple[str, bool]]) -> str:
    """The first paragraph of a section, as one line, when it is prose: a
    section that opens with code has none."""
    out: list[str] = []
    for line, fenced in lines:
        if not out and not fenced and not line.strip():
            continue
        if fenced or not line.strip() or (not out and re.match(r"( {4}|\t)", line)):
            break
        out.append(line.strip())
    return " ".join(out)


def gaps(body: str) -> list[str]:
    """What keeps an issue body under the bar; empty when it passes."""
    found = _sections(body)
    names = [name for name, _ in found]
    out = []
    if names != list(SECTIONS):
        out.append("the sections must be, in order: " + ", ".join(SECTIONS) + "; found: " + (", ".join(names) or "none"))
    for name, lines in found:
        if not any(line.strip() for line, _ in lines):
            out.append(f'"{name}" is empty; write "none"')
    parts = dict(found)
    if "Done when" in parts and not any(LIST_ITEM.match(line) for line, fenced in parts["Done when"] if not fenced):
        out.append('"Done when" holds no list line')
    if "Evidence" in parts and not NEW_CODE.fullmatch(_paragraph(parts["Evidence"])):
        out.append('"Evidence" must open, outside code, with "New code: none." or "New code: <what>, about <n> '
                   'lines; looked at <x>: <why it does not serve>; do less: <the option>."')
    return out


def file(title: str, body_file: Path, depth: str, *, decision: bool = False, parked: bool = False,
         assignee: str | None = None, blocked_by: str | None = None, parent: str | None = None,
         repo: str | None = None) -> str:
    """File one issue that passes the bar; returns its URL. The body is read
    once: the text checked is the text gh receives, on its standard input."""
    body = Path(body_file).read_text(encoding="utf-8")
    missing = gaps(body)
    if not title.strip():
        missing.insert(0, "the title is empty")
    if missing:
        raise Refused("the issue is under the bar:\n- " + "\n- ".join(missing))
    if leak.is_public(repo):
        leak.check_text(title + "\n\n" + body)
    command = ["issue", "create", "--title", title, "--body-file", "-"]
    for label in [name for name, wanted in (("decision", decision), ("parked", parked)) if wanted] + [depth]:
        command += ["--label", label]
    for flag, value in (("--assignee", assignee), ("--blocked-by", blocked_by), ("--parent", parent), ("--repo", repo)):
        if value:
            command += [flag, value]
    return _gh(*command, input=body).strip()


def reject(deposit: Path, reason: str) -> str:
    """Drop an inbox deposit; the reason is said, not stored."""
    deposit = Path(deposit)
    if not deposit.is_file():
        raise Refused(f"no deposit at {deposit}")
    if not reason.strip():
        raise Refused("a rejection carries its reason")
    deposit.unlink()
    return f"rejected {deposit.name}: {reason.strip()}"


def _items(lines: list[tuple[str, bool]]) -> list[str]:
    """The list items of a section, outside fences, each with the lines that
    continue it, as one line."""
    items: list[str] = []
    open_ = False
    for line, fenced in lines:
        if fenced or not line.strip():
            open_ = False
        elif LIST_ITEM.match(line):
            items.append(line.strip())
            open_ = True
        elif open_:
            items[-1] += " " + line.strip()
    return items


def _root() -> Path:
    """The decisions folder at the top of the checkout the command runs in:
    the repository gh reads the issue from."""
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode != 0:
        raise Refused("park close runs inside the repository whose decision it records")
    return Path(top.stdout.strip()) / "decisions"


def _here() -> dict[str, str]:
    """gh's environment for a decision: GH_REPO, which would point gh at
    another repository than this checkout's, is left out."""
    return {name: value for name, value in os.environ.items() if name != "GH_REPO"}


def _repository() -> str:
    """This checkout's repository, OWNER/NAME, as gh resolves it here."""
    return _gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner", env=_here()).strip()


def _view(number: int, repository: str) -> dict:
    return json.loads(_gh("issue", "view", str(number), "--repo", repository, "--json",
                          "number,title,state,stateReason,labels,url,closedAt", env=_here()))


def _ruled(item: str) -> bool:
    """A list line of "## Rulings": a real date, a real time or "time
    unknown", then the words in double quotes."""
    match = RULING.search(item)
    if not match:
        return False
    try:
        datetime.date.fromisoformat(match["date"])
        if match["hour"] is not None:
            datetime.time(int(match["hour"]), int(match["minute"]))
    except ValueError:
        return False
    return True


def _index(root: Path) -> list[dict]:
    index = root / "index.jsonl"
    text = index.read_text(encoding="utf-8") if index.exists() else ""
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _write(path: Path, text: str) -> None:
    """Whole or not at all: a reader never sees half a file."""
    part = path.with_name(f".{path.name}.part")
    part.write_text(text, encoding="utf-8")
    os.replace(part, path)


@contextlib.contextmanager
def _locked(root: Path):
    """One writer of the decisions folder at a time."""
    folder = os.open(root, os.O_RDONLY)
    try:
        fcntl.flock(folder, fcntl.LOCK_EX)
        yield
    finally:
        os.close(folder)


def _held_by_git(path: Path) -> bytes | None:
    """The bytes git holds for this file at HEAD, or None."""
    run = subprocess.run(["git", "-C", str(path.parent), "show", f"HEAD:./{path.name}"], capture_output=True)
    return run.stdout if run.returncode == 0 else None


def close(number: int, record_file: Path, name: str, *, replaces: int | None = None,
          repo: str | None = None) -> Path:
    """Record a decision GitHub shows closed as completed:
    `decisions/<number>-<name>.md` at the top of the checkout, and one line
    in `decisions/index.jsonl`, dated with GitHub's closing date. The issue
    is closed on GitHub first, on the user's word; this command refuses an
    open one and changes nothing on GitHub. The issue is read from this
    checkout's repository, and the folder must hold that repository's
    decisions only; `repo`, the one the issue was closed in, must be it.

    A decision it replaces must be active and committed as it stands, since
    its file goes; its bytes are compared once, before anything is written, so
    nobody edits `decisions/` while a close runs. A record or an index line
    already there for this decision refuses, named, and nothing changes: a run
    that stopped part-way is reconciled by a person, with git."""
    root = _root()
    repository = _repository()
    if repo is not None and repo != repository:
        raise Refused(f"#{number} was closed in {repo}, but this checkout's repository is {repository}: "
                      "record it in that repository's checkout")
    issue = _view(number, repository)
    if issue["number"] != number or not issue["url"].endswith(f"/{repository}/issues/{number}"):
        raise Refused(f"#{number} came back as {issue['url']}, not an issue of {repository}")
    if "decision" not in [label["name"] for label in issue["labels"]]:
        raise Refused(f"#{number} does not carry the label decision")
    if issue["state"] != "CLOSED" or issue.get("stateReason") != "COMPLETED" or not issue["closedAt"]:
        raise Refused(f"#{number} is not closed as completed on GitHub: close it there first, on the user's word "
                      f"(gh issue close {number} --repo {repository} --reason completed), then record it")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
        raise Refused(f"the short name {name!r} must be lower-case words joined by hyphens")
    target = root / f"{number}-{name}.md"

    root.mkdir(parents=True, exist_ok=True)
    with _locked(root):
        lines = _index(root)
        if strangers := [line["link"] for line in lines if f"/{repository}/issues/" not in line["link"]]:
            raise Refused(f"{root} records decisions of another repository than {repository}: {strangers[0]}")
        found = sorted(path.name for glob in (f"{number}-*.md", f".{number}-*.md.part") for path in root.glob(glob))
        found += ["its line in index.jsonl"] if any(line["number"] == number for line in lines) else []
        if found:
            raise Refused(f"#{number} already has {', '.join(found)} in {root}: nothing changes; if a run stopped "
                          "part-way, reconcile it with git")
        record = Path(record_file).read_text(encoding="utf-8").strip()
        parts = dict(_sections(record))
        rulings = _items(parts.get("Rulings", []))
        if not rulings or not all(_ruled(item) for item in rulings):
            raise Refused('the record needs "## Rulings" where every list line is a dated ruling: a real date, a '
                          'real time (or "time unknown") and the words in double quotes')
        if not any(line.strip() for line, _ in parts.get("Would overturn", [])):
            raise Refused('the record needs a filled "## Would overturn"')
        closed = issue["closedAt"][:10]
        head = f"# {issue['title']}\n\nDecision {number}, closed {closed}. Issue: {issue['url']}\n"
        if replaces is not None:
            head += f"Replaces decision {replaces}.\n"
        text = head + "\n" + record + "\n"
        older = None
        if replaces is not None:
            older = next((line for line in lines if line["number"] == replaces), None)
            if older is None:
                raise Refused(f"#{replaces} is not in {root / 'index.jsonl'}, so nothing can replace it")
            if older["replaced_by"] is not None:
                raise Refused(f"#{replaces} was already replaced by #{older['replaced_by']}")
            path = root / older["file"]
            if not path.is_file():
                raise Refused(f"{path} is missing: decision {replaces} is not active")
            if path.read_bytes() != _held_by_git(path):
                raise Refused(f"{path} is not committed as it stands: commit it first, or its words are lost "
                              "when it goes")
        _write(target, text)
        if older:
            older["replaced_by"] = number
        lines.append({"number": number, "title": issue["title"], "closed": closed, "link": issue["url"],
                      "file": target.name, "replaced_by": None})
        _write(root / "index.jsonl", "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines))
        if older:
            (root / older["file"]).unlink()
    return target
