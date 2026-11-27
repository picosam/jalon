"""The leak check, from inside: what refuses, and which commits a push
hands to the scan."""

import pytest

from conftest import LIST
from jalon import leak
from jalon.leak import Refused

A, B, H, ZERO = "a" * 40, "b" * 40, "c" * 40, "0" * 40


@pytest.fixture
def scans(monkeypatch):
    """Replaces the scans and the reads of git; returns the revisions the
    commit scan was given. `scans.texts` holds what the text scan was given;
    the destination holds H."""
    class Seen(list):
        texts: list[str]

    seen = Seen()
    seen.texts = []
    monkeypatch.setattr(leak, "check_commits", lambda repo, revs: seen.append(revs))
    monkeypatch.setattr(leak, "check_text", seen.texts.append)
    monkeypatch.setattr(leak, "is_public", lambda target=None: True)
    monkeypatch.setattr(leak, "_held", lambda repo, url: ([H], False))
    monkeypatch.setattr(leak, "_peel", lambda repo, obj: (obj, []))
    return seen


def test_the_list_is_in_the_home_folder_unless_named(tmp_path, monkeypatch):
    assert leak.list_path() == tmp_path / "home/.config/jalon/private.toml"
    monkeypatch.setenv(leak.LIST_ENV, "/elsewhere/list.toml")
    assert leak.list_path().as_posix() == "/elsewhere/list.toml"


def test_no_list_refuses_and_names_the_path(tmp_path):
    with pytest.raises(Refused, match="no private list at .*private.toml"):
        leak.check_text("anything")


def test_no_gitleaks_refuses(private_list, monkeypatch):
    monkeypatch.setattr(leak.shutil, "which", lambda name: None)
    with pytest.raises(Refused, match="gitleaks is not installed"):
        leak.check_text("anything")


def test_a_private_destination_is_not_scanned(scans, monkeypatch):
    monkeypatch.setattr(leak, "is_public", lambda target=None: False)
    leak.pre_push("origin", "url", [f"refs/heads/x {A} refs/heads/x {ZERO}"])
    assert scans == []


def test_a_public_destination_without_a_list_refuses_even_a_deletion(scans):
    with pytest.raises(Refused, match="no private list"):
        leak.pre_push("origin", "url", [f"(delete) {ZERO} refs/heads/x {A}"])


def test_a_deletion_scans_nothing(scans, private_list):
    leak.pre_push("origin", "url", [f"(delete) {ZERO} refs/heads/x {A}"])
    assert scans == [] and scans.texts == []


def test_a_new_ref_scans_what_the_destination_does_not_hold(scans, private_list):
    leak.pre_push("origin", "url", [f"refs/heads/x {A} refs/heads/x {ZERO}"])
    assert scans == [[A, "--not", H]]


def test_the_destination_and_not_the_clone_says_what_it_holds(scans, private_list):
    # The remote's old tip B, or a remote-tracking ref, decides nothing;
    # what the destination lists does.
    leak.pre_push("origin", "url", [f"refs/heads/x {A} refs/heads/x {B}"])
    assert scans == [[A, "--not", H]]


def test_each_ref_of_one_push_is_scanned_and_its_name_read(scans, private_list):
    leak.pre_push("origin", "url", [f"refs/heads/x {A} refs/heads/x {ZERO}", "", f"refs/tags/v1 {B} refs/tags/v1 {ZERO}"])
    assert [revs[0] for revs in scans] == [A, B]
    assert scans.texts == ["refs/heads/x\nrefs/tags/v1\n"]


def test_a_line_that_cannot_be_read_refuses(scans, private_list):
    with pytest.raises(Refused, match="cannot read the line"):
        leak.pre_push("origin", "url", ["refs/heads/x only-three fields"])


@pytest.mark.parametrize("answer, code, public", [
    ("PRIVATE\n", 0, False), ("INTERNAL\n", 0, True), ("PUBLIC\n", 0, True), ("", 0, True), ("private\n", 0, True),
    ("", 1, True), ("PRIVATE\n", 1, True)])
def test_only_a_private_answer_makes_a_destination_private(monkeypatch, answer, code, public):
    # An enterprise's INTERNAL is seen beyond the project, so it is scanned.
    class Run:
        returncode, stdout = code, answer
    monkeypatch.setattr(leak.subprocess, "run", lambda *args, **kwargs: Run)
    assert leak.is_public("owner/name") is public


def test_a_machine_without_gh_treats_every_destination_as_public(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("gh")
    monkeypatch.setattr(leak.subprocess, "run", missing)
    assert leak.is_public("owner/name") is True


# The machine's list alone may set a finding aside.

needs_gitleaks = pytest.mark.skipif(__import__("shutil").which("gitleaks") is None, reason="runs the real gitleaks")


@needs_gitleaks
def test_an_allow_comment_does_not_set_a_listed_name_aside(private_list):
    with pytest.raises(Refused, match="private-name"):
        leak.check_text("written by Zorblatt # gitleaks:allow\n")


@needs_gitleaks
def test_an_ignore_file_in_the_working_folder_does_not_set_a_finding_aside(private_list, alone):
    (alone / "folder").mkdir()
    (alone / "folder/a.txt").write_text("written by Zorblatt\n")
    (alone / ".gitleaksignore").write_text("folder/a.txt:private-name:1\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_dir("folder")


@needs_gitleaks
def test_an_ignore_file_in_the_scanned_folder_sets_nothing_aside(private_list, alone):
    # gitleaks is handed a copy under names of jalon's, where it finds no such file: it is one more text.
    (alone / "folder").mkdir()
    (alone / "folder/.gitleaksignore").write_text("a.txt:private-name:1\nfolder/a.txt:private-name:1\n")
    leak.check_dir("folder")  # the control: a clean folder passes with it
    (alone / "folder/a.txt").write_text("written by Zorblatt\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_dir("folder")


@needs_gitleaks
def test_an_allowance_in_the_list_itself_still_works(private_list):
    private_list.write_text(private_list.read_text() + "\n[[rules.allowlists]]\nregexTarget = \"line\"\n"
                            "regexes = ['''Zorblatt Avenue''']\n")
    leak.check_text("we met on Zorblatt Avenue\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_text("we met Zorblatt\n")


# What the commit and folder scans read.

def git(repo, *args, env=None, input=None):
    import os
    import subprocess
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, input=input,
                          env={**os.environ, **(env or {})})
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def committed(repo, name, text, message="a commit"):
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@needs_gitleaks
def test_a_replacement_object_does_not_hide_what_a_push_sends(private_list, alone):
    # `git replace` changes what git shows here, not what a push sends.
    git(alone, "init", "-q", "-b", "main")
    base = committed(alone, "a.txt", "a clean line\n")
    sent = committed(alone, "b.txt", "written by Zorblatt\n", "the one sent")
    leak.check_commits(alone, [base])  # the control: a clean history passes
    git(alone, "checkout", "-q", "--detach", base)
    shown = committed(alone, "b.txt", "a clean line\n", "the one shown")
    git(alone, "checkout", "-q", "main")
    git(alone, "replace", sent, shown)
    with pytest.raises(Refused, match="private-name"):
        leak.check_commits(alone, [sent, "--not", base])


@needs_gitleaks
def test_the_folder_scan_reads_the_bytes_it_checks(private_list, alone, monkeypatch):
    # A file that turns unreadable between the walk and gitleaks' read
    # is still checked, since gitleaks reads the copy the walk made.
    folder = alone / "folder"
    folder.mkdir()
    (folder / "a.txt").write_text("written by Zorblatt\n")
    real = leak._scan

    def later(*text, **kwargs):
        if kwargs.get("folder"):
            (folder / "a.txt").chmod(0)
        return real(*text, **kwargs)
    monkeypatch.setattr(leak, "_scan", later)
    try:
        with pytest.raises(Refused, match="private-name"):
            leak.check_dir(folder)
    finally:
        (folder / "a.txt").chmod(0o644)


# What the commit scan reads: the objects a push sends, whatever the clone shows.

@needs_gitleaks
@pytest.mark.parametrize("setting, value", [("log.showRoot", "false"), ("color.ui", "always"), ("diff.noprefix", "true")])
def test_a_commit_is_read_whatever_the_clone_displays(private_list, alone, setting, value):
    # Each of these changes what `git log -p` prints; none changes an object.
    git(alone, "init", "-q", "-b", "main")
    git(alone, "config", setting, value)
    root = committed(alone, "a.txt", "written by Zorblatt\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_commits(alone, [root])  # a first commit
    clean = committed(alone, "b.txt", "a clean line\n")
    leak.check_commits(alone, [clean, "--not", root])  # the control: a clean commit passes
    later = committed(alone, "c.txt", "also written by Zorblatt\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_commits(alone, [later, "--not", clean])


@needs_gitleaks
@pytest.mark.parametrize("name, rule", [("Zorb\rlatt", r"Zorb\rlatt"), ("Zorb\\latt.txt", r"Zorb\\latt"),
                                        ("notes\nZorblatt.txt", "Zorblatt"), ("Zorb/latt.txt", "Zorb/latt")])
def test_a_name_is_read_as_git_stores_it(private_list, alone, name, rule):
    # A carriage return, a backslash, a line break: a tree holds the name as it is. And a name that spans a
    # folder and a file is read as one path, from the top of the repository.
    private_list.write_text(LIST.replace("'''Zorblatt'''", f"'''{rule}'''"))
    git(alone, "init", "-q", "-b", "main")
    base = committed(alone, "a.txt", "a clean line\n")
    leak.check_commits(alone, [base])  # the control: a plain name passes
    (alone / name).parent.mkdir(exist_ok=True)
    tip = committed(alone, name, "a clean line\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_commits(alone, [tip, "--not", base])


@needs_gitleaks
@pytest.mark.parametrize("how", ["a folder moved whole", "two folders of the same content", "a parent with a line break"])
def test_a_path_is_read_whole_wherever_its_folder_comes_from(private_list, alone, how):
    # git sends a folder it has already sent by its name alone, and one of two alike once: the paths are
    # read from each commit instead, every one, as its tree spells it.
    private_list.write_text(LIST.replace("'''Zorblatt'''", "'''Second/Private'''"))
    git(alone, "init", "-q", "-b", "main")
    first = "front\nback/First" if how == "a parent with a line break" else "First"
    second = first.replace("First", "Second")
    (alone / first).mkdir(parents=True)
    (alone / first / "Private.txt").write_text("a clean line\n")
    git(alone, "add", "-A")
    git(alone, "commit", "-q", "-m", "one folder")
    base = git(alone, "rev-parse", "HEAD")
    leak.check_commits(alone, [base])  # the control: the same file under First passes
    if how == "a folder moved whole":
        git(alone, "mv", first, second)
    else:
        (alone / second).mkdir()
        (alone / second / "Private.txt").write_text("a clean line\n")
        git(alone, "add", "-A")
    git(alone, "commit", "-q", "-m", "another")
    with pytest.raises(Refused, match="private-name"):
        leak.check_commits(alone, ["HEAD", "--not", base])


@needs_gitleaks
def test_every_path_of_a_pushed_commit_is_read(private_list, alone):
    # A stated cost: a listed name in a path the destination already holds refuses a push that touches
    # another folder, until a commit renames that path away.
    git(alone, "init", "-q", "-b", "main")
    (alone / "docs").mkdir()
    held = committed(alone, "docs/Zorblatt.txt", "a clean line\n")
    other = committed(alone, "other.txt", "a clean line\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_commits(alone, [other, "--not", held])
    git(alone, "mv", "docs/Zorblatt.txt", "docs/plain.txt")
    git(alone, "commit", "-q", "-m", "renamed away")
    leak.check_commits(alone, ["HEAD", "--not", other])


@needs_gitleaks
def test_paths_are_read_from_the_top_wherever_the_scan_runs(private_list, alone, monkeypatch):
    # git lists a tree from the folder it runs in, unless told to list it whole.
    git(alone, "init", "-q", "-b", "main")
    (alone / "notes").mkdir()
    (alone / "other").mkdir()
    committed(alone, "other/a.txt", "a clean line\n")
    monkeypatch.chdir(alone / "other")
    leak.check_commits(".", ["HEAD"])  # the control: clean paths, read from a folder of the checkout
    committed(alone, "notes/Zorblatt.txt", "a clean line\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_commits(".", ["HEAD"])


@needs_gitleaks
@pytest.mark.parametrize("name, refused", [("plain", False), ("Zorblatt", True)])
def test_the_name_of_a_folder_that_holds_nothing_is_read(private_list, alone, name, refused):
    # git itself writes no such folder; a tool that writes trees can, and a push sends its name.
    git(alone, "init", "-q", "-b", "main")
    empty = git(alone, "mktree", input="")
    tree = git(alone, "mktree", input=f"040000 tree {empty}\t{name}\n")
    tip = git(alone, "commit-tree", tree, "-m", "a folder that holds nothing")
    if refused:
        with pytest.raises(Refused, match="private-name"):
            leak.check_commits(alone, [tip])
    else:
        leak.check_commits(alone, [tip])


POINTER = "version https://git-lfs.github.com/spec/v1\noid sha256:{}\nsize 12\n"


@needs_gitleaks
def test_a_git_lfs_pointer_is_one_more_text(private_list, alone):
    # A stated limit: what a pointer stands for goes to another server, and jalon does not look for pointers.
    git(alone, "init", "-q", "-b", "main")
    base = committed(alone, "a.txt", "a clean line\n")
    added = committed(alone, "data.csv", POINTER.format("a" * 64))
    leak.check_commits(alone, [added, "--not", base])
    named = committed(alone, "more.csv", POINTER.format("b" * 64) + "x-note Zorblatt\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_commits(alone, [named, "--not", added])


# What both scans read: every text, whatever it is called and however it is encoded.

def both_scans(alone, path, data):
    """A folder that holds `data` at `path`, and a commit that adds it; returns
    the folder and the range."""
    if not (alone / ".git").exists():
        git(alone, "init", "-q", "-b", "main")
        committed(alone, "first.txt", "a clean line\n")
    base = git(alone, "rev-parse", "HEAD")
    for top in (alone, alone / "folder"):
        (top / path).parent.mkdir(parents=True, exist_ok=True)
        (top / path).write_bytes(data)
    git(alone, "add", "-f", path)
    git(alone, "commit", "-q", "-m", "a commit")
    return alone / "folder", [git(alone, "rev-parse", "HEAD"), "--not", base]


@needs_gitleaks
@pytest.mark.parametrize("path", ["package-lock.json", "notes.svg", "node_modules/x.txt"])
def test_no_path_sets_a_text_aside(private_list, alone, path):
    # gitleaks' own rules skip such paths; it is handed none.
    folder, revs = both_scans(alone, path, b"a clean line\n")
    leak.check_dir(folder)
    leak.check_commits(alone, revs)
    folder, revs = both_scans(alone, path, b"written by Zorblatt\n")
    for scan in (lambda: leak.check_dir(folder), lambda: leak.check_commits(alone, revs)):
        with pytest.raises(Refused, match="private-name") as refusal:
            scan()
        assert f"file 0 is {path!r}" in str(refusal.value) or f"file 1 is {path!r}" in str(refusal.value)  # by its own path


@needs_gitleaks
@pytest.mark.parametrize("mark, encoding", [(b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")])
def test_a_utf_16_text_is_decoded_once(private_list, alone, capsys, mark, encoding):
    folder, revs = both_scans(alone, "export.csv", mark + "a clean line\n".encode(encoding))
    leak.check_dir(folder)
    leak.check_commits(alone, revs)
    folder, revs = both_scans(alone, "export.csv", mark + "written by Zorblatt\n".encode(encoding))
    for scan in (lambda: leak.check_dir(folder), lambda: leak.check_commits(alone, revs)):
        with pytest.raises(Refused, match="private-name"):
            scan()
    assert "not read" not in capsys.readouterr().err
    # With a NUL in it the text is named, since it may not be text, and is still read as decoded.
    folder, revs = both_scans(alone, "export.csv", mark + "written by Zorblatt\n\0".encode(encoding))
    for scan in (lambda: leak.check_dir(folder), lambda: leak.check_commits(alone, revs)):
        with pytest.raises(Refused, match="private-name"):
            scan()


@needs_gitleaks
@pytest.mark.parametrize("opening", ["%PDF-1.4", "{\\rtf1", "MZ"])
def test_a_text_is_handed_on_as_text_whatever_it_opens_with(private_list, alone, capsys, opening):
    # gitleaks skips, without a word, what opens as a binary file does. A text jalon decoded goes to it
    # after one line break, and so does a text on standard input.
    clean, listed = f"{opening} opens this text.\n", f"{opening} opens this text, by Zorblatt.\n"
    folder, revs = both_scans(alone, "notes.txt", clean.encode())
    leak.check_dir(folder)
    leak.check_commits(alone, revs)
    leak.check_text(clean)
    folder, revs = both_scans(alone, "notes.txt", listed.encode())
    for scan in (lambda: leak.check_dir(folder), lambda: leak.check_commits(alone, revs), lambda: leak.check_text(listed)):
        with pytest.raises(Refused, match="private-name"):
            scan()
    assert "not read" not in capsys.readouterr().err


@needs_gitleaks
def test_a_name_that_opens_as_a_binary_file_does_hides_no_other_name(private_list, alone):
    # The names of a folder go to gitleaks as one text, in order: the first one opens it.
    (alone / "folder").mkdir()
    (alone / "folder/%PDF-1.4 scan.txt").write_text("a clean line\n")
    leak.check_dir("folder")
    (alone / "folder/Zorblatt.txt").write_text("")
    with pytest.raises(Refused, match="private-name"):
        leak.check_dir("folder")


@needs_gitleaks
def test_a_text_in_another_encoding_is_named_and_its_bytes_still_go(private_list, alone, capsys):
    # Latin-1 is not UTF-8: the file is named as not read. A name written
    # plainly in its bytes is still matched; an accented one would not be.
    folder, revs = both_scans(alone, "notes.txt", "café, written by Zorblatt\n".encode("latin-1"))
    for scan in (lambda: leak.check_dir(folder), lambda: leak.check_commits(alone, revs)):
        with pytest.raises(Refused, match="private-name"):
            scan()
        assert "jalon: not read, as it is not text: 'notes.txt'" in capsys.readouterr().err


@needs_gitleaks
@pytest.mark.parametrize("pattern", ["", 'regex = """clean"""\n'])
def test_no_rule_with_a_path_is_applied(private_list, alone, pattern):
    # A stated limit: gitleaks is handed a number, not a path, so a rule with a path, alone or beside a
    # pattern, does not fire. A name is matched as text.
    private_list.write_text(LIST + f'\n[[rules]]\nid = "private-path"\npath = """secret-notes"""\n{pattern}')
    folder, revs = both_scans(alone, "secret-notes", b"a clean line\n")
    leak.check_dir(folder)
    leak.check_commits(alone, revs)
    private_list.write_text(LIST.replace("Zorblatt", "secret-notes"))
    for scan in (lambda: leak.check_dir(folder), lambda: leak.check_commits(alone, revs)):
        with pytest.raises(Refused, match="private-name"):
            scan()
