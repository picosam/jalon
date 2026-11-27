"""Nothing private reaches a public repository.

Every check runs gitleaks with the machine's private list: a gitleaks rule
file kept outside every repository, at ~/.config/jalon/private.toml unless
JALON_PRIVATE_LIST names another. A finding refuses. So does a missing list,
a missing gitleaks, or a gitleaks that fails: nothing passes without a clean
scan.

A destination is public unless GitHub says it is private. One that cannot be
read counts as public.
"""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

LIST_ENV = "JALON_PRIVATE_LIST"
NEXT_HOOK_ENV = "JALON_NEXT_PRE_PUSH"
# What the hook of `push` runs, in Python's isolated mode: the folder of this
# package, its first argument, goes first on the module search path.
HOOK = "import sys; sys.path.insert(0, sys.argv.pop(1)); from jalon.cli import main; sys.exit(main())"
# How a commit's content is read: a root commit's whole content whatever
# log.showRoot says, a merge's own changes (what its resolution adds to its
# two parents), every file as text whatever its attributes say, no colour
# whatever color.ui says, and no conversion or external tool between the
# file and the scan.
LOG = ["--root", "--no-color", "--diff-merges=remerge", "--text", "--no-textconv", "--no-ext-diff"]
# A pointer's first line, or its oid line, which alone changes when its object
# is replaced: a git -G pattern, which git reads as an extended expression.
LFS = "^(version https://git-lfs|oid sha256:)"


class Refused(Exception):
    """The check did not pass; the message says why."""


def list_path() -> Path:
    named = os.environ.get(LIST_ENV)
    return Path(named) if named else Path.home() / ".config" / "jalon" / "private.toml"


def _scan(mode: list[str], *, text: str | None = None) -> None:
    rules = list_path()
    if not rules.is_file():
        raise Refused(f"no private list at {rules}: nothing goes to a public repository from this machine")
    if shutil.which("gitleaks") is None:
        raise Refused("gitleaks is not installed: nothing goes to a public repository from this machine")
    # The list alone may set a finding aside: no `gitleaks:allow` comment, and
    # no .gitleaksignore, neither the working folder's nor the scanned one's
    # (gitleaks reads the scanned one whatever --gitleaks-ignore-path says).
    if mode[0] in ("dir", "git") and (Path(mode[-1]) / ".gitleaksignore").exists():
        raise Refused(f"{Path(mode[-1]) / '.gitleaksignore'} would set findings aside: only the private list may")
    with tempfile.TemporaryDirectory() as nothing:
        run = subprocess.run(
            ["gitleaks", *mode, "--config", str(rules), "--gitleaks-ignore-path", nothing, "--ignore-gitleaks-allow",
             "--no-banner", "--redact", "--verbose"],
            input=text, capture_output=True, text=True, env=_env(),
        )
    if run.returncode != 0:
        raise Refused((run.stdout + run.stderr).strip() or f"gitleaks exited {run.returncode}")


def _env() -> dict[str, str]:
    """git as the transfer sees it: no replacement object shows a history
    other than the one a push sends."""
    return {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}


def _git(repo: Path | str, *args: str, input: str | None = None, raw: bool = False):
    """git's output as text, or as bytes when `raw`: names read as bytes keep
    a carriage return, which text mode would turn into a line break."""
    try:
        run = subprocess.run(["git", "-C", str(repo), "-c", "core.quotePath=false", *args], input=input,
                             capture_output=True, env=_env(), **({} if raw else {"encoding": "utf-8"}))
        names = [name.decode("utf-8") for name in run.stdout.split(b"\0") if name] if raw else None
    except UnicodeDecodeError:
        raise Refused(f"git {' '.join(args)}: a name or a message is not UTF-8, so it cannot be checked") from None
    if run.returncode != 0:
        raise Refused(f"git {' '.join(args)}: {run.stderr.strip()}")
    return names if raw else run.stdout


def check_text(text: str) -> None:
    """A text bound for a public repository: a title, a body, a comment."""
    _scan(["stdin"], text=text)


def check_dir(path: Path | str) -> None:
    """A whole folder, as it stands on disk: every file's content, and every
    name and link target in it, which gitleaks does not read. Each file is
    read once, into a private copy, and the copy is what gitleaks scans, so
    the bytes checked are the bytes read. A file that cannot be read, or an
    entry that is neither a file, a folder nor a link, refuses: what is not
    read is not known to be clean."""
    root = Path(path)

    def unreadable(error: OSError) -> None:
        raise Refused(f"cannot read {error.filename}: {error.strerror}")

    names = []
    with tempfile.TemporaryDirectory() as copy:
        for folder, folders, files in os.walk(root, onerror=unreadable):  # a link to a folder is listed, not entered
            for entry in sorted(folders + files):
                full = Path(folder, entry)
                relative = full.relative_to(root)
                names.append(relative.as_posix())
                mode = full.lstat().st_mode
                if stat.S_ISLNK(mode):
                    names.append(os.readlink(full))
                    # In the copy a link becomes a file holding its target, so
                    # a rule on paths sees its path too.
                    (Path(copy) / relative).parent.mkdir(parents=True, exist_ok=True)
                    (Path(copy) / relative).write_text(os.readlink(full) + "\n")
                elif stat.S_ISREG(mode):
                    (Path(copy) / relative).parent.mkdir(parents=True, exist_ok=True)
                    try:
                        (Path(copy) / relative).write_bytes(full.read_bytes())
                    except OSError as error:
                        unreadable(error)
                elif not stat.S_ISDIR(mode):
                    raise Refused(f"{full} is neither a file, a folder nor a link")
        if (root / ".gitleaksignore").exists():
            raise Refused(f"{root / '.gitleaksignore'} would set findings aside: only the private list may")
        _scan(["stdin"], text="\n".join(names) + "\n")
        _scan(["dir", copy])


def check_commits(repo: Path | str, revs: list[str]) -> None:
    """The commits `git log <revs>` selects: what they add, a merge's own
    resolution included, and their messages, authors, committers and the
    paths they touch, which gitleaks does not read itself."""
    if not _git(repo, "rev-list", *revs).split():
        return
    if octopus := _git(repo, "rev-list", "--min-parents=3", *revs).split():
        raise Refused(f"{octopus[0]} merges more than two parents, whose own changes cannot be read: "
                      "merge them two at a time")
    if lfs := _git(repo, "log", *LOG, "--format=%H", "-G", LFS, *revs).split():
        raise Refused(f"{lfs[0]} holds a Git LFS pointer, whose content goes outside git, past this check")
    _scan(["git", "--log-opts=" + " ".join([*LOG, *revs]), str(repo)])
    names = _git(repo, "log", *LOG, "--name-only", "-z", "--format=", *revs, raw=True)
    metadata = _git(repo, "log", "--format=%H%n%an <%ae>%n%cn <%ce>%n%B", *revs)
    _scan(["stdin"], text=metadata + "\n".join(names) + "\n")


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
    ids = sorted({line.split()[0] for line in listed.splitlines() if line.strip()})
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
    if not is_public(url):
        return
    if not list_path().is_file():  # even a push that adds nothing, such as a deletion
        raise Refused(f"no private list at {list_path()}: nothing goes to a public repository from this machine")
    updates = []
    for line in lines:
        fields = line.split()
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
