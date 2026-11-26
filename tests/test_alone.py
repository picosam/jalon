"""The folder stands alone, so publishing it is a copy of the folder.

Two proofs. No file of the folder names a path outside it but the one the
design places outside every repository, the private list. And a copy of the
folder, put elsewhere, passes its own tests while every Python process of
that run (the test process, each `jalon` command it starts, and the hook
`jalon push` hands to git) reports each file it opens under the folder's
repository or the user's real home; none may be reported. The interpreter's
own files are the one exception named.

The proof's reach: jalon's Python processes,
observed, and the folder's text, read. git, gitleaks and gh's stand-in are not Python and their reads are not
observed: they run with the tests' empty home and no git configuration of the
machine's, and that is all this file says of them.
"""

import os
import pwd
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent.parent
REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir
LEFT_OUT = {".venv", "__pycache__", ".pytest_cache"}

# Spelled in pieces so that this file does not name them itself.
OUTSIDE = re.compile("|".join([r"/" + "Users/", r"/" + "home/", r"~" + "/"]))
THE_LIST = "~" + "/.config/jalon/private.toml"

AUDIT = '''
import json, os, sys
WATCHED = [os.path.realpath(p) for p in json.loads(os.environ["JALON_ALONE_WATCHED"])]
ALLOWED = [os.path.realpath(p) for p in {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix}]
REPORT = os.environ["JALON_ALONE_REPORT"]

def under(path, roots):
    return any(path == root or path.startswith(root + os.sep) for root in roots)

def hook(event, args):
    if event != "open" or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    path = os.path.realpath(os.fsdecode(args[0]))
    if under(path, WATCHED) and not under(path, ALLOWED) and path != REPORT:
        with open(REPORT, "a") as report:
            report.write(path + "\\n")

sys.addaudithook(hook)
'''


def files(folder):
    for path in sorted(folder.rglob("*")):
        if path.is_file() and not LEFT_OUT & set(path.relative_to(folder).parts):
            yield path


def test_no_file_names_a_path_outside_the_folder():
    named = []
    for path in files(FOLDER):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if OUTSIDE.search(line.replace(THE_LIST, "")):
                named.append(f"{path.relative_to(FOLDER)}:{number}: {line.strip()}")
    assert named == []


def audited(tmp_path, watched):
    """The environment that makes every Python process report what it opens
    under `watched`, and the file it reports to."""
    hooks = tmp_path / "audit"
    hooks.mkdir(exist_ok=True)
    (hooks / "sitecustomize.py").write_text(AUDIT)
    report = tmp_path / "opened.txt"
    report.write_text("")
    return {"PYTHONPATH": str(hooks), "JALON_ALONE_WATCHED": __import__("json").dumps([str(p) for p in watched]),
            "JALON_ALONE_REPORT": str(report)}, report


def test_the_audit_reports_a_read_outside(tmp_path):
    # The control: a file under a watched root, opened by a process the audit
    # covers, is reported.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("not jalon's\n")
    env, report = audited(tmp_path, [REAL_HOME, FOLDER.parent, outside])
    subprocess.run([sys.executable, "-c", f"open({str(outside / 'sentinel.txt')!r}).read()"],
                   env={**os.environ, **env}, check=True)
    assert report.read_text().splitlines() == [os.path.realpath(outside / "sentinel.txt")]


@pytest.mark.skipif(os.environ.get("JALON_ALONE") == "1", reason="already inside the copy")
def test_a_copy_of_the_folder_passes_its_own_tests_reading_nothing_outside(tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(FOLDER, copy, ignore=shutil.ignore_patterns(*LEFT_OUT))
    env, report = audited(tmp_path, [REAL_HOME, FOLDER.parent])
    env = {**os.environ, **env, "JALON_ALONE": "1", "PYTHONPATH": f"{copy / 'src'}{os.pathsep}{env['PYTHONPATH']}"}
    done = subprocess.run([sys.executable, "-m", "pytest", str(copy / "tests")],
                          cwd=copy, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-1000:]
    assert re.search(r"\b\d+ passed, 1 skipped", done.stdout), done.stdout[-300:]  # it ran, and skipped only this test
    assert report.read_text().splitlines() == []
