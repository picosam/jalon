"""commit: the commit rules `jalon.toml` declares under `[commits]`.

A subject reads `<type>[(<scope>)][!]: <subject>`, with a declared type and,
where a scope is written, a declared scope; git's own `Revert "..."` and
`Reapply "..."` pass where `revert` is a type. On the default branch a commit
may record only paths inside a declared data folder. `jalon commit message`
and `jalon commit branch` run from git's `commit-msg` and `pre-commit` hooks
and read the declaration from the tree `HEAD` records, fetching nothing;
`jalon status title` reads it from the default branch on GitHub.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from .leak import Refused

DECLARATION = "jalon.toml"
TYPES = ("change", "fix", "refactor", "guard", "test", "document", "design", "record", "deliver", "maintain", "revert")
KEYS = {"types", "scopes", "retired", "data"}
TYPE = re.compile(r"[a-z]+")
SCOPE = re.compile(r"[a-z]+(?:-[a-z]+)*")
SUBJECT = re.compile(r"(?P<type>[a-z]+)(?:\((?P<scope>[a-z-]+)\))?!?: \S.*")
REVERT = re.compile(r'(?:Revert|Reapply) ".*"')
FORM = "<type>[(<scope>)][!]: <subject>"


class Unreadable(Exception):
    """The declaration at HEAD cannot be read: the hook warns, and the commit lands."""


def rules(table: object) -> dict:
    """A `[commits]` table, checked: a problem is refused, naming it."""
    if not isinstance(table, dict):
        raise Refused("[commits] is not a table")
    if extra := sorted(set(table) - KEYS):
        raise Refused(f"[commits] holds {extra[0]!r}, which this version does not read")
    types, scopes = table.get("types", list(TYPES)), table.get("scopes", [])
    for key, names, form in (("types", types, TYPE), ("scopes", scopes, SCOPE)):
        if not (isinstance(names, list) and all(isinstance(name, str) and form.fullmatch(name) for name in names)):
            raise Refused(f"[commits] {key} must be a list of words of lowercase letters"
                          + (" or -" if key == "scopes" else ""))
    if both := sorted(set(types) & set(scopes)):
        raise Refused(f"[commits] declares {both[0]!r} both as a type and as a scope")
    retired = table.get("retired", {})
    if not isinstance(retired, dict):
        raise Refused("[commits] retired must be a table of a name and its redirect")
    for name, use in retired.items():
        if name in types or name in scopes:
            raise Refused(f"[commits] retires {name!r}, which it also declares")
        if not (isinstance(use, str) and use.strip()):
            raise Refused(f"[commits] retires {name!r} with a redirect that is not text")
    data = table.get("data", [])
    if not (isinstance(data, list) and all(isinstance(folder, str) and _inside(folder) for folder in data)):
        raise Refused("[commits] data must be a list of relative paths inside the repository")
    return {"types": set(types), "scopes": set(scopes), "retired": retired,
            "data": [folder.removesuffix("/").encode() for folder in data]}


def _inside(folder: str) -> bool:
    parts = folder.removesuffix("/").split("/")
    return not folder.startswith("/") and not any(part in ("", ".", "..") for part in parts)


def declared(text: str, where: str) -> dict | None:
    """The `[commits]` rules of a declaration's text, or None when it declares none."""
    try:
        table = tomllib.loads(text).get("commits")
    except tomllib.TOMLDecodeError as error:
        raise Refused(f"{DECLARATION} {where} is not TOML: {error}") from None
    return None if table is None else rules(table)


def judge(subject: str, vocabulary: dict) -> str | None:
    """Why `subject` fails the vocabulary, or None when it passes."""
    if not subject:
        return "the subject is empty"
    if REVERT.fullmatch(subject):
        return None if "revert" in vocabulary["types"] else "git's revert subject needs `revert` among the types"
    if not (found := SUBJECT.fullmatch(subject)):
        return f"it does not read {FORM}"
    for kind, name, declared_names in (("type", found["type"], vocabulary["types"]),
                                       ("scope", found["scope"], vocabulary["scopes"])):
        if name is None:
            continue
        if name in vocabulary["retired"]:
            return f"the {kind} {name!r} is retired; use {vocabulary['retired'][name]}"
        if name not in declared_names:
            return f"the {kind} {name!r} is not declared in {DECLARATION} [commits]"
    return None


def _git(*args: str, input: bytes | None = None) -> subprocess.CompletedProcess:
    """git, as bytes, never fetching a missing object and never reading a replacement for one: what is read is
    what this clone records."""
    return subprocess.run(["git", *args], input=input, capture_output=True,
                          env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1"})


def subject_of(message: bytes) -> str:
    """The subject git takes from a message: the first paragraph after `git stripspace --strip-comments`,
    its lines joined by one space."""
    run = _git("stripspace", "--strip-comments", input=message)
    if run.returncode != 0:
        raise Refused(f"git stripspace: {run.stderr.decode(errors='replace').strip()}")
    try:
        text = run.stdout.decode()
    except UnicodeDecodeError:
        raise Refused("the commit message is not UTF-8") from None
    first = text.split("\n\n", 1)[0].strip("\n")
    return " ".join(first.split("\n"))


def _at_head() -> dict | None:
    """The `[commits]` rules of `jalon.toml` in the tree HEAD records; None when there is none."""
    if _git("rev-parse", "--verify", "--quiet", "HEAD^{commit}").returncode != 0:
        return None
    listed = _git("ls-tree", "-z", "--full-tree", "HEAD", "--", DECLARATION)
    if listed.returncode != 0:
        raise Unreadable(f"git ls-tree HEAD: {listed.stderr.decode(errors='replace').strip()}")
    if not listed.stdout:
        return None
    _, kind, oid = listed.stdout.split(b"\t", 1)[0].split()
    if kind != b"blob":
        raise Unreadable(f"{DECLARATION} at HEAD is not a file")
    blob = _git("cat-file", "blob", oid.decode())
    if blob.returncode != 0:
        raise Unreadable(f"git cat-file: {blob.stderr.decode(errors='replace').strip()}")
    try:
        return declared(blob.stdout.decode(), "at HEAD")
    except UnicodeDecodeError:
        raise Unreadable(f"{DECLARATION} at HEAD is not UTF-8") from None
    except Refused as refusal:
        raise Unreadable(str(refusal)) from None


def _warn(problem: object) -> None:
    print(f"jalon: warning: {problem}; the commit rules are not checked until it is fixed", file=sys.stderr)


def message(path: Path) -> None:
    """git's `commit-msg` hook: the subject of the message file against the vocabulary at HEAD."""
    try:
        vocabulary = _at_head()
    except Unreadable as problem:
        return _warn(problem)
    if vocabulary is None:
        return
    try:
        subject = subject_of(path.read_bytes())
    except OSError as error:
        raise Refused(f"cannot read the commit message: {error}") from None
    if why := judge(subject, vocabulary):
        raise Refused(f"the commit subject {subject!r}: {why}")


def branch() -> None:
    """git's `pre-commit` hook: on the default branch, every staged path inside a declared data folder."""
    try:
        vocabulary = _at_head()
    except Unreadable as problem:
        return _warn(problem)
    head = _git("symbolic-ref", "--quiet", "HEAD")
    if vocabulary is None or head.returncode != 0:
        return  # nothing declared, or detached: no branch
    origin = _git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if origin.returncode != 0:
        return _warn("this clone has no refs/remotes/origin/HEAD to name the default branch "
                     "(git remote set-head origin --auto sets it)")
    default = origin.stdout.removesuffix(b"\n").removeprefix(b"refs/remotes/origin/")
    if head.stdout.removesuffix(b"\n") != b"refs/heads/" + default:
        return
    staged = _git("diff", "--cached", "--name-only", "-z", "--no-renames", "--ignore-submodules=none", "HEAD")
    if staged.returncode != 0:
        raise Refused(f"git diff --cached: {staged.stderr.decode(errors='replace').strip()}")
    for path in staged.stdout.split(b"\0"):
        if path and not any(path.startswith(folder + b"/") for folder in vocabulary["data"]):
            raise Refused(f"{default.decode(errors='replace')} is the default branch, and "
                          f"{path.decode(errors='replace')!r} lies outside every data folder {DECLARATION} declares: "
                          f"commit on a branch (git switch -c <branch>), or, as a person committing deliberately, "
                          f"git commit --no-verify")
