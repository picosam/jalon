"""The leak check, from inside: what refuses, and which commits a push
hands to the scan."""

import pytest

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
def test_an_ignore_file_in_the_scanned_folder_refuses(private_list, alone):
    (alone / "folder").mkdir()
    (alone / "folder/a.txt").write_text("a clean line\n")
    (alone / "folder/.gitleaksignore").write_text("folder/b.txt:private-name:1\n")
    with pytest.raises(Refused, match="set findings aside"):
        leak.check_dir("folder")


@needs_gitleaks
def test_an_allowance_in_the_list_itself_still_works(private_list):
    private_list.write_text(private_list.read_text() + "\n[[rules.allowlists]]\nregexTarget = \"line\"\n"
                            "regexes = ['''Zorblatt Avenue''']\n")
    leak.check_text("we met on Zorblatt Avenue\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_text("we met Zorblatt\n")


# What the commit and folder scans read.

def git(repo, *args, env=None):
    import os
    import subprocess
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
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

    def later(mode, **kwargs):
        if mode[0] == "dir":
            (folder / "a.txt").chmod(0)
        return real(mode, **kwargs)
    monkeypatch.setattr(leak, "_scan", later)
    try:
        with pytest.raises(Refused, match="private-name"):
            leak.check_dir(folder)
    finally:
        (folder / "a.txt").chmod(0o644)


# What the commit and folder scans read: settings and shapes that hide content.

@needs_gitleaks
@pytest.mark.parametrize("show_root", ["true", "false"])
def test_a_root_commit_is_read_whatever_the_clone_shows(private_list, alone, show_root):
    # Log.showRoot decides whether git log shows a root commit's content.
    git(alone, "init", "-q", "-b", "main")
    git(alone, "config", "log.showRoot", show_root)
    root = committed(alone, "a.txt", "written by Zorblatt\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_commits(alone, [root])
    clean = committed(alone, "b.txt", "a clean line\n")
    leak.check_commits(alone, [clean, "--not", root])  # the control: an ordinary commit after it


@needs_gitleaks
@pytest.mark.parametrize("colour", ["auto", "always"])
def test_a_commit_is_read_whatever_colours_the_clone_sets(private_list, alone, colour):
    # Colour escapes inside a line would split the listed words the rules match.
    git(alone, "init", "-q", "-b", "main")
    git(alone, "config", "color.ui", colour)
    root = committed(alone, "a.txt", "written by Zorblatt\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_commits(alone, [root])
    clean = committed(alone, "b.txt", "a clean line\n")
    leak.check_commits(alone, [clean, "--not", root])  # the control: a clean commit passes
    later = committed(alone, "c.txt", "written by Zorblatt\n")
    with pytest.raises(Refused, match="private-name"):
        leak.check_commits(alone, [later, "--not", clean])


@needs_gitleaks
def test_a_name_is_read_as_git_stores_it(private_list, alone):
    # A carriage return in a name reaches the rules as it is, not as a line break.
    private_list.write_text(private_list.read_text() + "\n[[rules]]\nid = \"private-return\"\nregex = 'Zorb\\rlatt'\n")
    git(alone, "init", "-q", "-b", "main")
    base = committed(alone, "a.txt", "a clean line\n")
    leak.check_commits(alone, [base])  # the control: a plain name passes
    tip = committed(alone, "Zorb\rlatt", "a clean line\n")
    with pytest.raises(Refused, match="private-return"):
        leak.check_commits(alone, [tip, "--not", base])


POINTER = "version https://git-lfs.github.com/spec/v1\noid sha256:{}\nsize 12\n"


@needs_gitleaks
def test_a_push_that_introduces_or_changes_an_lfs_pointer_is_refused(private_list, alone):
    # Replacing a pointer's object changes its oid line, not its version line.
    git(alone, "init", "-q", "-b", "main")
    base = committed(alone, "a.txt", "a clean line\n")
    added = committed(alone, "data.csv", POINTER.format("a" * 64))
    with pytest.raises(Refused, match="Git LFS pointer"):
        leak.check_commits(alone, [added, "--not", base])
    changed = committed(alone, "data.csv", POINTER.format("b" * 64))
    with pytest.raises(Refused, match="Git LFS pointer"):
        leak.check_commits(alone, [changed, "--not", added])
    docs = committed(alone, "README.md", "a clean line\n")
    leak.check_commits(alone, [docs, "--not", changed])  # a stated limit: that pointer is already public


@needs_gitleaks
def test_a_path_rule_sees_a_link_as_it_sees_a_file(private_list, alone):
    # A rule on paths alone, on a stored link and on a regular file.
    private_list.write_text(private_list.read_text() + '\n[[rules]]\nid = "private-path"\npath = """secret-notes"""\n')
    folder = alone / "folder"
    folder.mkdir()
    (folder / "a.txt").write_text("a clean line\n")
    (folder / "allowed-link").symlink_to("a.txt")
    leak.check_dir(folder)  # the control: an allowed path
    (folder / "secret-notes").symlink_to("a.txt")
    with pytest.raises(Refused, match="private-path"):
        leak.check_dir(folder)
    (folder / "secret-notes").unlink()
    (folder / "secret-notes").write_text("a clean line\n")
    with pytest.raises(Refused, match="private-path"):
        leak.check_dir(folder)
