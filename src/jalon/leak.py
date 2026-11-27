"""Nothing private reaches a public repository.

Every check runs gitleaks with the machine's private list: a gitleaks rule
file kept outside every repository, at ~/.config/jalon/private.toml unless
JALON_PRIVATE_LIST names another. A finding refuses. So does a missing list,
a missing gitleaks, or a gitleaks that fails: nothing passes without a clean
scan.

A destination is public unless GitHub says it is private. One that cannot be
read counts as public; so does a push's destination not written as an address.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

LIST_ENV = "JALON_PRIVATE_LIST"
NEXT_HOOK_ENV = "JALON_NEXT_PRE_PUSH"
HOOK = "import sys; sys.path.insert(0, sys.argv.pop(1)); from jalon.cli import main; sys.exit(main())"


class Refused(Exception):
    """The check did not pass; the message says why."""


def list_path() -> Path:
    named = os.environ.get(LIST_ENV)
    return Path(named) if named else Path.home() / ".config" / "jalon" / "private.toml"


def _scan(text: str | None = None, *, folder: str | None = None, names: list[str] | None = None) -> None:
    """gitleaks with the machine's list, on a text (after one line break, as in `_hand`) or on a folder `_hand`
    filled, read from inside it so that no path above it counts. A refusal says what each number is called."""
    rules = list_path()
    if not rules.is_file():
        raise Refused(f"no private list at {rules}: nothing goes to a public repository from this machine")
    if shutil.which("gitleaks") is None:
        raise Refused("gitleaks is not installed: nothing goes to a public repository from this machine")
    # The list alone sets a finding aside: no `gitleaks:allow` comment, no .gitleaksignore of the working folder.
    with tempfile.TemporaryDirectory() as nothing:
        run = subprocess.run(
            ["gitleaks", *(["dir", "."] if folder else ["stdin"]), "--config", str(rules.absolute()),
             "--gitleaks-ignore-path", nothing, "--ignore-gitleaks-allow", "--no-banner", "--redact", "--verbose"],
            input=text and "\n" + text, cwd=folder, capture_output=True, encoding="utf-8",
            errors="replace")  # gitleaks quotes what it finds
    if run.returncode != 0:
        said = (run.stdout + run.stderr).strip() or f"gitleaks exited {run.returncode}"
        found = sorted({int(file) for file in re.findall(r"(?m)^File: +(\d+)$", said)}) if names else []
        raise Refused(said + "".join(f"\nfile {file} is {names[file]!r}" for file in found if file < len(names)))


def _env() -> dict[str, str]:
    """git as a push sees it: no replacement object stands in for the one sent."""
    return {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}


def _git(repo: Path | str, *args: str, input: str = "") -> str:
    """What git prints, byte for byte: no line break of a name is rewritten on the way."""
    run = subprocess.run(["git", "-C", str(repo), *args], input=input.encode(), capture_output=True, env=_env())
    if run.returncode != 0:
        raise Refused(f"git {' '.join(args)}: {run.stderr.decode(errors='replace').strip()}")
    try:
        return run.stdout.decode()
    except UnicodeDecodeError:
        raise Refused(f"git {' '.join(args)}: a name or a message is not UTF-8, so it cannot be checked") from None


def _hand(copy: str, names: list[str], name: str, data: bytes) -> None:
    """One file or blob for gitleaks, under its number in `names`: gitleaks sets files aside by their path
    (a lock file, an image, `node_modules`), and a number gives it none. Text is decoded once, as UTF-8, or as
    UTF-16 by its byte-order mark, and goes on after one line break: gitleaks skips what opens as a binary file
    does (`%PDF`, `MZ`). Anything else is named, and its bytes go on unopened."""
    wide = data[:2] in (b"\xff\xfe", b"\xfe\xff")
    try:
        text = data.decode("utf-16" if wide else "utf-8")
        data = b"\n" + text.encode()
    except UnicodeDecodeError:
        text = "\0"
    if "\0" in text:  # undecoded, or a NUL in it: not known to be text
        print(f"jalon: not read, as it is not text: {name!r}", file=sys.stderr)
    Path(copy, str(len(names))).write_bytes(data)
    names.append(name)


def check_text(text: str) -> None:
    """A text bound for a public repository: a title, a body, a comment."""
    _scan(text)


def check_dir(path: Path | str) -> None:
    """A whole folder, as it stands on disk: every file's content, read once
    and handed on by `_hand`, and every name and link target in it. A file
    that cannot be read, or an entry that is neither a file, a folder nor a
    link, refuses: what is not read is not known to be clean."""
    root = Path(path)
    def unreadable(error: OSError) -> None:
        raise Refused(f"cannot read {error.filename}: {error.strerror}")

    names, files = [], []
    with tempfile.TemporaryDirectory() as copy:
        for folder, folders, entries in os.walk(root, onerror=unreadable):  # a link to a folder is listed, not entered
            for entry in sorted(folders + entries):
                full = Path(folder, entry)
                names.append(full.relative_to(root).as_posix())
                mode = full.lstat().st_mode
                if stat.S_ISLNK(mode):
                    names.append(os.readlink(full))
                elif stat.S_ISREG(mode):
                    try:
                        _hand(copy, files, names[-1], full.read_bytes())
                    except OSError as error:
                        unreadable(error)
                elif not stat.S_ISDIR(mode):
                    raise Refused(f"{full} is neither a file, a folder nor a link")
        _scan("\n".join(names) + "\n")
        _scan(folder=copy, names=files)


def check_commits(repo: Path | str, revs: list[str]) -> None:
    """What a push of the commits `git rev-list <revs>` selects would send: the
    objects `git rev-list --objects <revs>` lists, each read whole and as git
    stores it, one at a time, with no patch and no display setting between.
    A blob is handed on as a file is, a commit or a tag as its whole text.
    The paths are those of each commit, every one, the destination's too:
    from the top of the repository, a folder that holds nothing included."""
    git = ["git", "-C", str(repo)]
    said, where, files = [], {}, []
    for commit in _git(repo, "rev-list", *revs).split():
        for entry in _git(repo, "ls-tree", "-r", "-t", "-z", "--full-tree", commit).split("\0")[:-1]:
            where.setdefault(entry.split(maxsplit=3)[2], set()).add(entry.partition("\t")[2])  # an object's paths
    with tempfile.TemporaryDirectory() as copy:
        with (subprocess.Popen([*git, "rev-list", "--objects", "--no-object-names", *revs], stdout=subprocess.PIPE,
                               env=_env()) as lister,
              subprocess.Popen([*git, "cat-file", "--batch=%(objectname) %(objecttype) %(objectsize)"],
                               stdin=lister.stdout, stdout=subprocess.PIPE, env=_env()) as reader):
            lister.stdout.close()
            for head in iter(reader.stdout.readline, b""):
                oid, kind, size = [*head.decode().split(), ""][:3]
                if not size.isdigit():  # an object this clone lacks
                    raise Refused(f"git cat-file: {head.decode().strip()}")
                data, _ = reader.stdout.read(int(size)), reader.stdout.read(1)
                if kind == "blob":
                    _hand(copy, files, min(where.get(oid, [oid])), data)  # one path, where it sits at several
                elif kind != "tree":
                    said.append(data)
        if lister.returncode or reader.returncode:
            raise Refused(f"git could not list or read the objects of {' '.join(revs)}")
        try:
            _scan("\n".join([b"\n".join(said).decode(), *sorted(set().union(*where.values())), ""]))
        except UnicodeDecodeError:
            raise Refused("a name or a message is not UTF-8, so it cannot be checked") from None
        _scan(folder=copy, names=files)


def is_public(target: str | None = None) -> bool:
    """`target` is a repository as `gh` takes one (OWNER/REPO or a URL);
    None is the repository of the current directory."""
    command = ["gh", "repo", "view", *([target] if target else []), "--json", "visibility", "--jq", ".visibility"]
    try:
        run = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError:
        return True
    return not (run.returncode == 0 and run.stdout.strip() == "PRIVATE")


def _held(repo: Path | str, url: str) -> tuple[list[str], bool]:
    """The commits the destination holds that this clone has too, read from
    the destination itself: a clone's remote-tracking refs can be stale, or
    belong to another URL. Also whether it holds a tip this clone lacks, below
    which commits it already has may be scanned again."""
    try:
        listed = _git(repo, "ls-remote", url)
    except Refused as refusal:
        raise Refused(f"cannot read what {url} holds: {refusal}") from None
    ids = sorted({line.split()[0] for line in listed.split("\n") if line.strip()})  # a ref's name may hold U+2028
    found = _git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                 input="".join(f"{id}^{{commit}}\n" for id in ids))
    held = sorted({line.split()[0] for line in found.splitlines() if line.endswith(" commit")})
    return held, any(line.endswith(" missing") for line in found.splitlines())


def _peel(repo: Path | str, obj: str) -> tuple[str, list[str]]:
    """The commit a pushed object comes down to, and the text of each tag
    object on the way: a tag's tagger and message reach the destination too."""
    texts = []
    while (kind := _git(repo, "cat-file", "-t", obj).strip()) == "tag":
        text = _git(repo, "cat-file", "tag", obj)
        texts.append(text)
        obj = text.split("\n", 1)[0].removeprefix("object ").strip()
    if kind != "commit":
        raise Refused(f"{obj} is a {kind}: jalon pushes commits, and tags of commits, only")
    return obj, texts


def pre_push(remote: str, url: str, lines: list[str], repo: Path | str = ".") -> None:
    """git's pre-push hook: `remote` and `url` are its two arguments, `lines`
    its standard input, one `<local ref> <local id> <remote ref> <remote id>`
    per ref. Scans what each ref would add to the destination: the commits it
    does not hold, the ref's own name, and every tag object on the way."""
    # Only an address is asked: gh reads `team/records` as a repository on GitHub, where git reads a folder.
    if re.match(r"[a-zA-Z][\w+.-]*://|[^/:@]+@[^/:]+:", url) and not is_public(url):  # scheme://, or user@host:
        return
    if not list_path().is_file():  # even a push that adds nothing, such as a deletion
        raise Refused(f"no private list at {list_path()}: nothing goes to a public repository from this machine")
    updates = []
    for line in lines:
        fields = line.split(" ") if line else []  # git's separators: a ref name may hold other spaces
        if not fields:
            continue
        if len(fields) != 4:
            raise Refused(f"pre-push: cannot read the line {line!r}")
        if set(fields[1]) != {"0"}:  # a deletion adds nothing
            updates.append((fields[1], fields[2]))
    if not updates:
        return
    held, unknown = _held(repo, url)
    texts = []
    for local, name in updates:
        commit, tags = _peel(repo, local)
        texts += [name, *tags]
        try:
            check_commits(repo, [commit, "--not", *held])
        except Refused as refusal:
            if unknown:
                raise Refused(f"{refusal}\nThe destination holds commits this clone does not, so commits it already "
                              "has may have been read as new: fetch, then push again.") from None
            raise
    check_text("\n".join(texts) + "\n")


def push(args: list[str]) -> int:
    """`git push <args>` with the check forced on, for a clone whose hook is
    not installed. git itself works out what is pushed and hands it to the
    hook. An argument that git could read as skipping hooks is refused, in any
    spelling and any place. The repository's own pre-push hook, if it has one,
    runs after the check with the same input, and either can stop the push.
    The hook runs the jalon that wrote it: isolated (-I), Python leaves out
    the folder git runs it in, PYTHONPATH and the user's own packages."""
    # Every argument, `--` or not: an option's value can be `--` itself.
    skips = [arg for arg in args if len(arg) > len("--no-") and "--no-verify".startswith(arg)]
    if skips:
        raise Refused(f"{skips[0]} would skip the check: jalon push never skips it")
    own = Path(_git(".", "rev-parse", "--git-path", "hooks/pre-push").strip()).absolute()
    env = {name: value for name, value in os.environ.items() if name != NEXT_HOOK_ENV}
    if own.is_file() and os.access(own, os.X_OK):
        env[NEXT_HOOK_ENV] = str(own)
    with tempfile.TemporaryDirectory() as hooks:
        hook = Path(hooks) / "pre-push"
        package = shlex.quote(str(Path(__file__).resolve().parents[1]))
        hook.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -I -c {shlex.quote(HOOK)} {package} '
                        'leak pre-push "$@"\n')
        hook.chmod(0o755)
        return subprocess.run(["git", "-c", f"core.hooksPath={hooks}", "push", *args], env=env).returncode


def next_hook(remote: str, url: str, lines: str) -> int:
    """The repository's own pre-push hook, which `push` names, run after the
    check with git's arguments and the same input; 0 when it has none."""
    own = os.environ.get(NEXT_HOOK_ENV)
    if not own:
        return 0
    env = {name: value for name, value in os.environ.items() if name != NEXT_HOOK_ENV}
    return subprocess.run([own, remote, url], input=lines, text=True, env=env).returncode
