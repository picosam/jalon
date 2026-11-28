"""start: begin an issue's work on its linked branch, in this checkout.

`gh issue develop` makes, reuses and checks out the branch. What is ours: an
issue with no criteria is refused, the time the criteria were read as of is
recorded on the issue, and a hook this clone lacks is named.
"""

from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlsplit

from . import leak
from .leak import Refused
from .park import LIST_ITEM, _gh, _here, _repository, _sections

HOOKS = ("pre-push", "pre-commit", "commit-msg")
QUERY = ("query($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) {"
         " defaultBranchRef { name } issue(number: $number) { title body state lastEditedAt createdAt"
         " linkedBranches(first: 100) { nodes { ref { name } } } } } }")


def _read(repo: str, number: int) -> tuple[dict, str]:
    """The issue and the repository's default branch, in one call."""
    address = urlsplit(repo)
    owner, name = address.path.strip("/").removesuffix(".git").split("/")
    data = json.loads(_gh("api", "graphql", "--hostname", address.hostname or "github.com", "-f", f"query={QUERY}",
                          "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={number}", env=_here()))
    repository = data["data"]["repository"]
    if not repository["issue"]:
        raise Refused(f"issue {number} was not found in {repo}")
    return repository["issue"], repository["defaultBranchRef"]["name"]


def _criteria(body: str) -> str | None:
    """Why the body holds no criteria; None when it does."""
    sections = dict(_sections(body))
    if "Done when" not in sections:
        return "its body has no ## Done when section"
    if not any(LIST_ITEM.match(line) for line, fenced in sections["Done when"] if not fenced):
        return '"Done when" holds no list line'
    return None


def _missing_hooks() -> list[str]:
    missing = []
    for hook in HOOKS:
        path = leak._git(".", "rev-parse", "--git-path", f"hooks/{hook}").removesuffix("\n")
        if not (os.path.isfile(path) and os.access(path, os.X_OK)):
            missing.append(f"jalon: the {hook} hook is missing or not executable at {path}")
    return missing


def start(number: int, name: str | None = None) -> str:
    """Check out issue `number`'s linked branch here, making it if the issue has none; returns the branch."""
    repo = _repository()
    issue, default = _read(repo, number)
    if issue["state"] != "OPEN":
        raise Refused(f"issue {number} is {issue['state'].lower()}, not open")
    if why := _criteria(issue["body"] or ""):
        raise Refused(f"issue {number} has no criteria to start from: {why}")
    linked = [node["ref"]["name"] for node in issue["linkedBranches"]["nodes"] if node.get("ref")]
    if len(linked) > 1:
        raise Refused(f"issue {number} has {len(linked)} linked branches: {', '.join(linked)}")
    if linked:
        branch = linked[0]
    else:
        words = name or "-".join(re.findall(r"[a-z0-9]+", issue["title"].lower())[:3])
        if not words:
            raise Refused(f"issue {number}'s title holds no ASCII word to name its branch: give --name")
        branch = f"{number}-{words}"
    for line in _missing_hooks():
        print(line, file=sys.stderr)
    _gh("issue", "develop", str(number), "--repo", repo, "--base", default, "--name", branch, "--checkout", env=_here())
    read_as = (f"as this issue's body was last edited at {issue['lastEditedAt']}" if issue["lastEditedAt"]
               else f"as this issue was filed at {issue['createdAt']}; its body was never edited")
    comment = f"Started by `jalon start` on branch `{branch}`. The criteria were read {read_as}."
    if leak.is_public(repo):
        leak.check_text(comment)
    _gh("issue", "comment", str(number), "--repo", repo, "--body-file", "-", input=comment, env=_here())
    return branch
