"""jalon's command line."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import commit, leak, park, start, status


def _parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="jalon", description=__import__("jalon").__doc__)
    commands = top.add_subparsers(dest="command", required=True)

    parked = commands.add_parser("park", help="file a scoped issue, record a closed decision")
    verbs = parked.add_subparsers(dest="verb", required=True)
    file = verbs.add_parser("file", help="file one issue that passes the nine-section bar")
    file.add_argument("--title", required=True)
    file.add_argument("--body-file", required=True, type=Path)
    file.add_argument("--depth", required=True, choices=park.DEPTHS, help="the review depth, set as a label")
    file.add_argument("--decision", action="store_true", help="label it decision")
    file.add_argument("--parked", action="store_true", help="label it parked")
    file.add_argument("--assignee")
    file.add_argument("--blocked-by")
    file.add_argument("--parent")
    file.add_argument("--repo")
    close = verbs.add_parser("close", help="record a decision GitHub shows closed as completed, in decisions/")
    close.add_argument("number", type=int)
    close.add_argument("--record-file", required=True, type=Path)
    close.add_argument("--name", required=True, help="the record's short name: decisions/<number>-<name>.md")
    close.add_argument("--replaces", type=int, help="an earlier decision this one replaces")
    close.add_argument("--repo", help="the repository it was closed in, as `gh repo view --json url` prints it")

    leaked = commands.add_parser("leak", help="check that nothing private goes to a public repository")
    kinds = leaked.add_subparsers(dest="verb", required=True)
    kinds.add_parser("text", help="a text on standard input")
    kinds.add_parser("dir", help="a whole folder").add_argument("path", type=Path)
    kinds.add_parser("commits", help="the commits `git log <revs>` selects").add_argument("revs", nargs=argparse.REMAINDER)
    hook = kinds.add_parser("pre-push", help="git's pre-push hook: its two arguments, its standard input")
    hook.add_argument("remote")
    hook.add_argument("url")

    commands.add_parser("push", help="git push with the leak check forced on").add_argument("args", nargs=argparse.REMAINDER)

    checked = commands.add_parser("commit", help="the commit rules jalon.toml declares, run from git's hooks")
    hooks = checked.add_subparsers(dest="verb", required=True)
    hooks.add_parser("message", help="git's commit-msg hook: the subject against the declared vocabulary"
                     ).add_argument("file", type=Path, help="the commit message file git hands the hook")
    hooks.add_parser("branch", help="git's pre-commit hook: on the default branch, only the declared data folders")

    started = commands.add_parser("start", help="check out an issue's linked branch here, making it if it has none")
    started.add_argument("number", type=int, help="the issue")
    started.add_argument("--name", help="the branch's name after `<number>-`, when the issue has no linked branch")

    posted = commands.add_parser("status", help="post jalon/tests or jalon/title on a pull request's head commit")
    posts = posted.add_subparsers(dest="verb", required=True)
    posts.add_parser("tests", help="run the tests the default branch declares, here, and post jalon/tests"
                     ).add_argument("number", type=int, help="the pull request")
    posts.add_parser("title", help="check the title against the private list and post jalon/title"
                     ).add_argument("number", type=int, help="the pull request")
    return top


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["push"]:  # everything after it is git's, options first included
        try:
            return leak.push(argv[1:])
        except leak.Refused as refusal:
            print(f"jalon: refused: {refusal}", file=sys.stderr)
            return 1
    args = _parser().parse_args(argv)
    try:
        match args.command, getattr(args, "verb", None):
            case "park", "file":
                print(park.file(args.title, args.body_file, args.depth, decision=args.decision, parked=args.parked,
                                assignee=args.assignee, blocked_by=args.blocked_by, parent=args.parent,
                                repo=args.repo))
            case "park", "close":
                print(os.path.relpath(park.close(args.number, args.record_file, args.name, replaces=args.replaces,
                                                 repo=args.repo)))
            case "leak", "text":
                leak.check_text(sys.stdin.read())
            case "leak", "dir":
                leak.check_dir(args.path)
            case "leak", "commits":
                leak.check_commits(".", args.revs)
            case "leak", "pre-push":
                lines = sys.stdin.read()
                leak.pre_push(args.remote, args.url, lines.split("\n"))
                return leak.next_hook(args.remote, args.url, lines)
            case "commit", "message":
                commit.message(args.file)
            case "commit", "branch":
                commit.branch()
            case "start", _:
                print(start.start(args.number, args.name))
            case "status", "tests":
                return status.tests(args.number)
            case "status", "title":
                return status.title(args.number)
    except leak.Refused as refusal:
        print(f"jalon: refused: {refusal}", file=sys.stderr)
        return 1
    return 0
