"""status: post `jalon/tests` and `jalon/title` on a pull request's head commit.

The tests are the commands listed under `[tests]` in `jalon.toml`, read as the
repository's default branch holds it on GitHub, so a pull request cannot change
the commands that judge it. They run in this checkout, which must be clean and
at the pull request's head. The title is checked against the private list on a
repository that is not private, and every description sent to such a
repository passes that list first.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from urllib.parse import urlsplit

from . import leak
from .leak import Refused
from .park import _gh, _here, _repository

DECLARATION = "jalon.toml"


def _api(repo: str) -> tuple[str, str]:
    """The host of a repository's address and its path in GitHub's API."""
    address = urlsplit(repo)
    return address.hostname or "github.com", "repos/" + address.path.strip("/").removesuffix(".git")


def _pull(repo: str, number: int) -> dict:
    return json.loads(_gh("pr", "view", str(number), "--repo", repo, "--json", "state,headRefOid,title", env=_here()))


def _git(*args: str) -> str:
    return leak._git(".", *args).strip()


def declared_tests(text: str) -> list[str]:
    """The commands of a declaration's `[tests]` table, refusing one this
    version cannot run: only `place = "here"` and a list of commands."""
    try:
        tests = tomllib.loads(text).get("tests")
    except tomllib.TOMLDecodeError as error:
        raise Refused(f"{DECLARATION} on the default branch is not TOML: {error}") from None
    if not isinstance(tests, dict):
        raise Refused(f"{DECLARATION} on the default branch has no [tests] table")
    if extra := sorted(set(tests) - {"place", "commands"}):
        raise Refused(f"[tests] holds {extra[0]!r}, which this version does not read")
    if tests.get("place") != "here":
        raise Refused(f'[tests] has place = {tests.get("place")!r}: jalon status tests runs place = "here" only')
    commands = tests.get("commands")
    if not (isinstance(commands, list) and commands and all(isinstance(each, str) and each.strip() for each in commands)):
        raise Refused("[tests] commands must be a list of one or more commands")
    return commands


def _post(repo: str, sha: str, context: str, state: str, description: str) -> None:
    """Visibility is read now, not when the command started: a run can take minutes."""
    if leak.is_public(repo):
        leak.check_text(description)
    host, path = _api(repo)
    _gh("api", f"{path}/statuses/{sha}", "--hostname", host, "-f", f"state={state}", "-f", f"context={context}",
        "-f", f"description={description}", env=_here())
    print(f"{context}: {state} on {sha[:7]}: {description}")


def tests(number: int) -> int:
    """Run the declared tests here, at pull request `number`'s head, and post `jalon/tests`."""
    repo = _repository()
    pull = _pull(repo, number)
    if pull["state"] != "OPEN":
        raise Refused(f"pull request {number} is {pull['state'].lower()}, not open: nothing is posted")
    head = pull["headRefOid"]
    if (here := _git("rev-parse", "HEAD")) != head:
        raise Refused(f"this checkout is at {here[:7]}, not at pull request {number}'s head {head[:7]}")
    if _git("status", "--porcelain"):
        raise Refused("git status shows changes in this checkout: the tests would not run the head commit")
    host, path = _api(repo)
    commands = declared_tests(_gh("api", f"{path}/contents/{DECLARATION}", "--hostname", host,
                                  "-H", "Accept: application/vnd.github.raw+json", env=_here()))
    top = leak._git(".", "rev-parse", "--show-toplevel").removesuffix("\n")  # a name may end in a space
    for place, command in enumerate(commands, 1):
        print(f"jalon: {place} of {len(commands)}: {command}", file=sys.stderr, flush=True)
        code = subprocess.run(["sh", "-c", command], cwd=top, env={**os.environ, "PWD": top}).returncode
        if code != 0:
            _post(repo, head, "jalon/tests", "failure",
                  f"Command {place} of {len(commands)} exited {code} at {head[:7]}; run here by jalon status tests")
            return 1
    if (now := _git("rev-parse", "HEAD")) != head:
        raise Refused(f"the checkout moved from {head[:7]} to {now[:7]} while the commands ran: nothing is posted")
    _post(repo, head, "jalon/tests", "success",
          f"{len(commands)} commands passed at {head[:7]}; run here by jalon status tests")
    return 0


def title(number: int) -> int:
    """Check pull request `number`'s title against the private list and post `jalon/title`."""
    repo = _repository()
    if not leak.is_public(repo):
        raise Refused("on a private repository jalon status title checks nothing yet: nothing is posted")
    pull = _pull(repo, number)
    try:
        leak.check_text(pull["title"])
    except Refused as refusal:
        print(f"jalon: the title: {refusal}", file=sys.stderr)
        _post(repo, pull["headRefOid"], "jalon/title", "failure",
              "The title does not pass the private list; posted by jalon status title")
        return 1
    _post(repo, pull["headRefOid"], "jalon/title", "success",
          "The title passes the private list; posted by jalon status title")
    return 0
