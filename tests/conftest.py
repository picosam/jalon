"""Every test runs alone: an empty home, an empty folder, no git
configuration of the machine's, and no private list unless it makes one."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"

BODY = """## Why

Because the source says so.

## Done when

- `true` exits 0.

## Out of scope

none

## Rulings it touches

none

## Waits on

none

## Evidence

New code: none.

Checked today: `true`.

## Assumptions

none

## Related items

none
"""

LIST = """title = "a test list"

[extend]
useDefault = true

[[rules]]
id = "private-name"
description = "a listed name"
regex = '''Zorblatt'''
"""

GH = """#!/bin/sh
# A stand-in for gh: it logs each call and answers from files.
printf '%s\\n' "$*${GH_REPO:+ GH_REPO=$GH_REPO}" >> "$GH_STANDIN/calls"
prev=
for arg; do
  [ "$prev" = --body-file ] && [ "$arg" = - ] && cat > "$GH_STANDIN/stdin"
  prev=$arg
done
key="$1-$2"
case "$*" in *"--json url"*) key=repo-url;; esac
code=0
[ -f "$GH_STANDIN/$key.exit" ] && code=$(cat "$GH_STANDIN/$key.exit")
[ -f "$GH_STANDIN/$key.out" ] && cat "$GH_STANDIN/$key.out"
[ "$key" = issue-close ] && [ -f "$GH_STANDIN/issue-view.closed" ] && cp "$GH_STANDIN/issue-view.closed" "$GH_STANDIN/issue-view.out"
exit "$code"
"""


@pytest.fixture(autouse=True)
def alone(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("JALON_PRIVATE_LIST", raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "A Tester")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "tester@example.org")
    return work


@pytest.fixture
def body(alone):
    path = alone / "body.md"
    path.write_text(BODY)
    return path


@pytest.fixture
def private_list(tmp_path, monkeypatch):
    path = tmp_path / "home" / ".config" / "jalon" / "private.toml"
    path.parent.mkdir(parents=True)
    path.write_text(LIST)
    return path


@pytest.fixture
def outside(tmp_path, monkeypatch):
    """What a test from outside needs on PATH: the real command under the
    name `jalon`, and a stand-in `gh`. Returns the stand-in's folder: write
    `<word>-<word>.out` and `.exit` there to set an answer (`repo-url` for the
    read of the checkout's repository); read `calls`. Like the installed
    script, the command does not look for modules in the folder it runs in
    (-P); it finds its own source first and hands PYTHONPATH on untouched."""
    bin = tmp_path / "bin"
    bin.mkdir()
    standin = tmp_path / "gh"
    standin.mkdir()
    (standin / "calls").write_text("")
    (bin / "gh").write_text(GH)
    (bin / "jalon").write_text(f'#!/bin/sh\nexec "{sys.executable}" -P -c "import sys; sys.path.insert(0, sys.argv.pop(1)); '
                               f'from jalon.cli import main; sys.exit(main())" "{SRC}" "$@"\n')
    for tool in ("gh", "jalon"):
        (bin / tool).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(SRC), *filter(None, [os.environ.get("PYTHONPATH")])]))
    monkeypatch.setenv("GH_STANDIN", str(standin))
    return standin


def run(*command, cwd=None, input=None, env=None):
    return subprocess.run([str(part) for part in command], cwd=cwd, input=input, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})
