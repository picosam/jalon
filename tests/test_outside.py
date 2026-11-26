"""From outside: the real command, run in a scratch repository with a
stand-in gh. One test for each command's main path, and one for each refusal
that guards the boundary no private thing may cross.

Nothing here imports the tool. gitleaks and git are the real ones.
"""

import json
import shutil

import pytest

from conftest import run

pytestmark = pytest.mark.skipif(shutil.which("gitleaks") is None, reason="these tests run the real gitleaks")

NAME = "Zorblatt"  # the one name on the test list


def answer(standin, key, out="", code=0):
    (standin / f"{key}.out").write_text(out)
    (standin / f"{key}.exit").write_text(str(code))


def calls(standin, key):
    return [line for line in (standin / "calls").read_text().splitlines() if line.startswith(key)]


@pytest.fixture
def repo(alone, outside, tmp_path):
    """A clone with one pushed commit and a bare remote GitHub calls public."""
    remote = tmp_path / "remote.git"
    run("git", "init", "-q", "--bare", "-b", "main", remote)
    run("git", "init", "-q", "-b", "main", alone)
    run("git", "remote", "add", "origin", remote, cwd=alone)
    commit(alone, "first.txt", "a clean line\n", "the first commit")
    assert run("git", "push", "-q", "origin", "main", cwd=alone).returncode == 0
    run("git", "fetch", "-q", "origin", cwd=alone)
    answer(outside, "repo-view", "PUBLIC\n")
    return alone


def commit(repo, name, text, message, env=None):
    (repo / name).write_text(text)
    run("git", "add", name, cwd=repo)
    assert run("git", "commit", "-q", "-m", message, cwd=repo, env=env).returncode == 0
    return run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()


def remote_tip(repo, ref="refs/heads/main"):
    return run("git", "ls-remote", "origin", ref, cwd=repo).stdout.split()[:1]


# park: the three main paths.

def test_park_file_files_one_issue(outside, body):
    answer(outside, "repo-view", "PRIVATE\n")
    answer(outside, "issue-create", "https://example.org/8\n")
    done = run("jalon", "park", "file", "--title", "A title", "--body-file", body, "--depth", "quick", "--decision")
    assert (done.returncode, done.stdout) == (0, "https://example.org/8\n")
    assert calls(outside, "issue create") == ["issue create --title A title --body-file - --label decision --label quick"]
    assert (outside / "stdin").read_text() == body.read_text()
    # The visibility read and the filing, and no lookup of open issues.
    assert [line.split(" --")[0] for line in calls(outside, "")] == ["repo view", "issue create"]


def test_park_file_takes_no_deposit(outside, body, alone):
    # A kept deposit is filed, then removed with park reject.
    (alone / "deposit.md").write_text("a proposal")
    done = run("jalon", "park", "file", "--title", "A title", "--body-file", body, "--depth", "quick",
               "--deposit", "deposit.md")
    assert done.returncode == 2 and (alone / "deposit.md").exists() and calls(outside, "") == []


def test_park_reject_drops_the_deposit(outside, alone):
    (alone / "deposit.md").write_text("a proposal")
    done = run("jalon", "park", "reject", "deposit.md", "--reason", "covered by #3")
    assert (done.returncode, done.stdout) == (0, "rejected deposit.md: covered by #3\n")
    assert not (alone / "deposit.md").exists()


def decision(outside, alone, state="CLOSED"):
    """Issue 7, a decision GitHub shows closed as completed (or open), in a
    checkout of a private repository."""
    run("git", "init", "-q", "-b", "main", alone)
    answer(outside, "repo-view", "PRIVATE\n")
    answer(outside, "repo-name", "owner/name\n")
    closed = {"stateReason": "COMPLETED", "closedAt": "2026-01-03T09:00:00Z"} if state == "CLOSED" else \
        {"stateReason": None, "closedAt": None}
    answer(outside, "issue-view", json.dumps({"number": 7, "title": "Which option?", "state": state,
                                              "labels": [{"name": "decision"}], "url": "https://github.com/owner/name/issues/7",
                                              **closed}))
    (alone / "record.md").write_text('## Rulings\n\n- 2026-01-02 10:15 UTC: "Yes."\n\n## Would overturn\n\nA measured cost.\n')


def test_park_close_records_the_decision_github_closed(outside, alone):
    decision(outside, alone)
    done = run("jalon", "park", "close", "7", "--record-file", "record.md", "--name", "which-option")
    assert (done.returncode, done.stdout) == (0, "decisions/7-which-option.md\n"), done.stderr
    assert '"Yes."' in (alone / "decisions/7-which-option.md").read_text()
    assert json.loads((alone / "decisions/index.jsonl").read_text())["closed"] == "2026-01-03"
    assert [line.split()[:2] for line in calls(outside, "")] == [["repo", "view"], ["issue", "view"]]


def test_park_close_refuses_an_open_decision(outside, alone):
    # The issue is closed on GitHub first: nothing of ours changes GitHub.
    decision(outside, alone, state="OPEN")
    done = run("jalon", "park", "close", "7", "--record-file", "record.md", "--name", "which-option")
    assert done.returncode == 1 and "close it there first" in done.stderr
    assert [line.split()[:2] for line in calls(outside, "")] == [["repo", "view"], ["issue", "view"]]
    assert not (alone / "decisions").exists()


def test_park_close_from_a_subfolder_records_at_the_top(outside, alone):
    # The record belongs to the repository gh reads the issue from.
    decision(outside, alone)
    (alone / "sub").mkdir()
    done = run("jalon", "park", "close", "7", "--record-file", "../record.md", "--name", "which-option",
               cwd=alone / "sub")
    assert (done.returncode, done.stdout) == (0, "../decisions/7-which-option.md\n"), done.stderr
    assert (alone / "decisions/7-which-option.md").exists() and not (alone / "sub/decisions").exists()


def test_park_close_names_no_other_repository(outside, alone):
    # --repo names the checkout's own or refuses, and GH_REPO is left out.
    decision(outside, alone)
    done = run("jalon", "park", "close", "7", "--record-file", "record.md", "--name", "which-option",
               "--repo", "owner/other")
    assert done.returncode == 1 and "this checkout's repository is owner/name" in done.stderr
    assert calls(outside, "issue view") == [] and not (alone / "decisions").exists()
    done = run("jalon", "park", "close", "7", "--record-file", "record.md", "--name", "which-option",
               env={"GH_REPO": "owner/other"})
    assert done.returncode == 0, done.stderr
    assert calls(outside, "") and not [line for line in calls(outside, "") if "GH_REPO=" in line]
    assert calls(outside, "issue view")[0].startswith("issue view 7 --repo owner/name ")


# The push path: its main path, then the boundary.

def test_a_clean_push_to_a_public_repository_goes_through(repo, private_list):
    tip = commit(repo, "second.txt", "another clean line\n", "the second commit")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode == 0, done.stderr
    assert remote_tip(repo) == [tip]


def test_a_listed_name_in_a_file_stops_the_push(repo, private_list):
    before = remote_tip(repo)
    commit(repo, "second.txt", f"written by {NAME}\n", "the second commit")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode != 0 and "private-name" in done.stderr
    assert remote_tip(repo) == before


def test_a_secret_in_a_file_stops_the_push(repo, private_list):
    before = remote_tip(repo)
    token = "gh" + "p_" + "x7Kq2Lm9Zt4Rv8Wb3Ny6Hc1Jd5Fg0Sa2Pe7U"  # a made-up token of GitHub's shape
    commit(repo, "second.txt", f"token = {token}\n", "the second commit")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode != 0
    assert remote_tip(repo) == before


def test_a_listed_name_in_a_commit_message_stops_the_push(repo, private_list):
    before = remote_tip(repo)
    commit(repo, "second.txt", "a clean line\n", f"as {NAME} asked")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode != 0 and "private-name" in done.stderr
    assert remote_tip(repo) == before


@pytest.mark.parametrize("who", ["AUTHOR", "COMMITTER"])
def test_a_listed_name_as_author_or_committer_stops_the_push(repo, private_list, who):
    before = remote_tip(repo)
    commit(repo, "second.txt", "a clean line\n", "the second commit", env={f"GIT_{who}_NAME": f"{NAME} Q"})
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode != 0 and "private-name" in done.stderr
    assert remote_tip(repo) == before


def test_without_a_list_nothing_is_pushed_to_a_public_repository(repo):
    before = remote_tip(repo)
    commit(repo, "second.txt", "a clean line\n", "the second commit")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode != 0 and "no private list at" in done.stderr and "private.toml" in done.stderr
    assert remote_tip(repo) == before


def test_a_destination_that_cannot_be_read_counts_as_public(repo, outside):
    answer(outside, "repo-view", "", code=1)
    before = remote_tip(repo)
    commit(repo, "second.txt", "a clean line\n", "the second commit")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode != 0 and "no private list at" in done.stderr
    assert remote_tip(repo) == before


def test_a_private_destination_is_not_scanned(repo, outside):
    # No list on this machine, and a listed name in the commit: a scan would
    # refuse twice over. The push goes through because none runs.
    answer(outside, "repo-view", "PRIVATE\n")
    tip = commit(repo, "second.txt", f"written by {NAME}\n", "the second commit")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode == 0, done.stderr
    assert remote_tip(repo) == [tip]


def test_only_the_commits_being_pushed_are_scanned(repo, outside, private_list):
    # A listed name already on the remote, pushed while it was private.
    answer(outside, "repo-view", "PRIVATE\n")
    commit(repo, "old.txt", f"written by {NAME}\n", "an old commit")
    assert run("jalon", "push", "origin", "main", cwd=repo).returncode == 0
    answer(outside, "repo-view", "PUBLIC\n")
    # An update, a new branch and a tag that add only clean commits pass.
    tip = commit(repo, "new.txt", "a clean line\n", "a new commit")
    assert run("jalon", "push", "origin", "main", cwd=repo).returncode == 0
    assert remote_tip(repo) == [tip]
    assert run("jalon", "push", "origin", "main:refs/heads/other", cwd=repo).returncode == 0
    run("git", "tag", "v1", cwd=repo)
    assert run("jalon", "push", "origin", "v1", cwd=repo).returncode == 0


def test_a_clean_forced_update_with_its_option_first_goes_through(repo, private_list):
    # Git's options come before the remote as often as after it.
    run("git", "commit", "-q", "--amend", "-m", "the first commit, reworded", cwd=repo)
    tip = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    done = run("jalon", "push", "--force", "origin", "main", cwd=repo)
    assert done.returncode == 0, done.stderr
    assert remote_tip(repo) == [tip]


@pytest.mark.parametrize("command", [["--no-verify", "origin", "main"], ["origin", "main", "--no-verify"],
                                     ["--no-verif", "origin", "main"], ["--no-veri", "origin", "main"]])
def test_an_option_that_skips_hooks_is_refused(repo, private_list, command):
    # Git's own opt-out of hooks, in any spelling and place git accepts.
    before = remote_tip(repo)
    commit(repo, "second.txt", f"written by {NAME}\n", "the second commit")
    done = run("jalon", "push", *command, cwd=repo)
    assert done.returncode == 1 and "would skip the check" in done.stderr
    assert remote_tip(repo) == before


def own_hook(repo, code):
    """The repository's own pre-push hook: it keeps its arguments and input
    beside the clone and exits with `code`."""
    hook = repo / ".git/hooks/pre-push"
    hook.write_text(f'#!/bin/sh\necho "$@" > ../hook-args\ncat > ../hook-input\nexit {code}\n')
    hook.chmod(0o755)
    return repo.parent


def test_the_repositorys_own_hook_runs_after_the_check_with_the_same_input(repo, private_list):
    # A clone's own pre-push work, such as Git LFS's, is not dropped.
    beside = own_hook(repo, 0)
    [old] = remote_tip(repo)
    url = run("git", "remote", "get-url", "origin", cwd=repo).stdout.strip()
    tip = commit(repo, "second.txt", "a clean line\n", "the second commit")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode == 0, done.stderr
    assert remote_tip(repo) == [tip]
    assert (beside / "hook-args").read_text() == f"origin {url}\n"
    assert (beside / "hook-input").read_text() == f"refs/heads/main {tip} refs/heads/main {old}\n"


def test_the_repositorys_own_hook_can_still_stop_a_clean_push(repo, private_list):
    own_hook(repo, 1)
    before = remote_tip(repo)
    commit(repo, "second.txt", "a clean line\n", "the second commit")
    assert run("jalon", "push", "origin", "main", cwd=repo).returncode != 0
    assert remote_tip(repo) == before


def test_a_forced_update_and_a_tag_scan_their_new_commits(repo, private_list):
    before = remote_tip(repo)
    run("git", "commit", "-q", "--amend", "-m", f"rewritten for {NAME}", cwd=repo)
    done = run("jalon", "push", "--force", "origin", "main", cwd=repo)
    assert done.returncode == 1 and "private-name" in done.stderr and remote_tip(repo) == before
    run("git", "tag", "v1", cwd=repo)
    done = run("jalon", "push", "origin", "v1", cwd=repo)
    assert done.returncode != 0 and remote_tip(repo, "refs/tags/v1") == []


def test_a_deletion_passes(repo, private_list):
    assert run("jalon", "push", "origin", "main:refs/heads/other", cwd=repo).returncode == 0
    done = run("jalon", "push", "origin", ":refs/heads/other", cwd=repo)
    assert done.returncode == 0, done.stderr
    assert remote_tip(repo, "refs/heads/other") == []


def test_a_remote_pointed_elsewhere_scans_what_the_new_destination_lacks(repo, outside, private_list, tmp_path):
    # Origin's remote-tracking ref still names a commit of its old,
    # private destination; the new one never received it.
    answer(outside, "repo-view", "PRIVATE\n")
    commit(repo, "old.txt", f"written by {NAME}\n", "an old commit")
    assert run("jalon", "push", "origin", "main", cwd=repo).returncode == 0
    fresh = tmp_path / "fresh.git"
    run("git", "init", "-q", "--bare", "-b", "main", fresh)
    run("git", "remote", "set-url", "origin", fresh, cwd=repo)
    answer(outside, "repo-view", "PUBLIC\n")
    commit(repo, "new.txt", "a clean line\n", "a new commit")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode == 1 and "private-name" in done.stderr
    assert remote_tip(repo) == []


def test_a_name_on_a_ref_stops_its_push_even_on_a_commit_already_there(repo, private_list):
    # A new branch's name is published, whatever it points at.
    done = run("jalon", "push", "origin", f"main:refs/heads/for-{NAME}", cwd=repo)
    assert done.returncode == 1 and "private-name" in done.stderr
    assert remote_tip(repo, f"refs/heads/for-{NAME}") == []


@pytest.mark.parametrize("how", ["message", "tagger"])
def test_an_annotated_tag_is_read_whole(repo, private_list, how):
    # On a commit the destination already holds, the tag object alone is new.
    message, env = ("release", {"GIT_COMMITTER_NAME": f"{NAME} Q"}) if how == "tagger" else (f"for {NAME}", None)
    run("git", "tag", "-a", "v1", "-m", message, cwd=repo, env=env)
    done = run("jalon", "push", "origin", "v1", cwd=repo)
    assert done.returncode == 1 and "private-name" in done.stderr
    assert remote_tip(repo, "refs/tags/v1") == []


def test_a_clean_annotated_tag_goes_through(repo, private_list):
    run("git", "tag", "-a", "v1", "-m", "release one", cwd=repo)
    done = run("jalon", "push", "origin", "v1", cwd=repo)
    assert done.returncode == 0, done.stderr
    assert remote_tip(repo, "refs/tags/v1") != []


def test_a_tag_of_a_tree_is_refused(repo, private_list):
    run("git", "tag", "-a", "tree", "-m", "a tree", "HEAD^{tree}", cwd=repo)
    done = run("jalon", "push", "origin", "tree", cwd=repo)
    assert done.returncode == 1 and "is a tree" in done.stderr


@pytest.mark.parametrize("resolution, refused", [("a resolved line\n", False), (f"resolved by {NAME}\n", True)])
def test_a_merge_is_read_for_what_its_resolution_adds(repo, private_list, resolution, refused):
    # Both parents are clean; only the resolution can hold the name.
    run("git", "checkout", "-q", "-b", "side", cwd=repo)
    commit(repo, "first.txt", "the side's line\n", "the side")
    run("git", "checkout", "-q", "main", cwd=repo)
    commit(repo, "first.txt", "main's line\n", "main")
    run("git", "merge", "-q", "side", cwd=repo)
    tip = commit(repo, "first.txt", resolution, "merged")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    if refused:
        assert done.returncode == 1 and "private-name" in done.stderr
    else:
        assert done.returncode == 0, done.stderr
        assert remote_tip(repo) == [tip]


@pytest.mark.parametrize("how", ["new", "renamed", "empty"])
def test_a_name_in_a_path_stops_the_push(repo, private_list, how):
    # A clean file can carry the name in its path alone.
    before = remote_tip(repo)
    if how == "renamed":
        run("git", "mv", "first.txt", f"{NAME}.txt", cwd=repo)
        run("git", "commit", "-q", "-m", "renamed", cwd=repo)
    else:
        (repo / "notes").mkdir()
        commit(repo, f"notes/{NAME}.txt", "" if how == "empty" else "a clean line\n", "the second commit")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode == 1 and "private-name" in done.stderr
    assert remote_tip(repo) == before


def test_a_skip_after_an_option_whose_value_is_a_double_dash_is_refused(repo, private_list, tmp_path):
    # `-o --` gives -o the value `--`; git still reads what follows as options.
    run("git", "config", "receive.advertisePushOptions", "true", cwd=tmp_path / "remote.git")
    before = remote_tip(repo)
    commit(repo, "second.txt", f"written by {NAME}\n", "the second commit")
    done = run("jalon", "push", "-o", "--", "origin", "main", "--no-verify", cwd=repo)
    assert done.returncode == 1 and "would skip the check" in done.stderr
    assert remote_tip(repo) == before


@pytest.mark.parametrize("listed", [False, True])
def test_a_file_whose_diff_is_turned_off_is_still_read(repo, private_list, listed):
    # `-diff` in .gitattributes hides a text file's patch.
    (repo / ".gitattributes").write_text("*.ps -diff\n")
    tip = commit(repo, "notes.ps", f"written by {NAME if listed else 'someone'}\n", "the second commit")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    if listed:
        assert done.returncode == 1 and "private-name" in done.stderr
    else:
        assert done.returncode == 0, done.stderr
        assert remote_tip(repo) == [tip]


def test_a_merge_of_more_than_two_parents_is_refused(repo, private_list):
    # Remerge reads two parents only, so an octopus is refused by its shape.
    for side in ("one", "two"):
        run("git", "checkout", "-q", "-b", side, "main", cwd=repo)
        commit(repo, f"{side}.txt", "a clean line\n", side)
    run("git", "checkout", "-q", "main", cwd=repo)
    commit(repo, "main.txt", "a clean line\n", "main's own")
    assert run("git", "merge", "-q", "-m", "octopus", "one", "two", cwd=repo).returncode == 0
    assert len(run("git", "rev-parse", "HEAD^@", cwd=repo).stdout.split()) == 3
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode == 1 and "more than two parents" in done.stderr


ACCENTED = '\n[[rules]]\nid = "accented-name"\nregex = """Zörblatt"""\n'


@pytest.mark.parametrize("name, refused", [("notes-Zörblatt.txt", True), ("notes-café.txt", False)])
def test_a_name_with_accents_is_read_as_it_is_spelled(repo, alone, private_list, tmp_path, name, refused):
    # Git quotes such a path unless told not to; both checks see the real name.
    private_list.write_text(private_list.read_text() + ACCENTED)
    tip = commit(repo, name, "a clean line\n", "the second commit")
    pushed = run("jalon", "push", "origin", "main", cwd=repo)
    export = tmp_path / "export"
    export.mkdir()
    (export / name).write_text("a clean line\n")
    folder = run("jalon", "leak", "dir", export)
    if refused:
        assert pushed.returncode == 1 and "accented-name" in pushed.stderr
        assert folder.returncode == 1 and "accented-name" in folder.stderr
    else:
        assert pushed.returncode == 0, pushed.stderr
        assert remote_tip(repo) == [tip] and folder.returncode == 0, folder.stderr


def test_a_refusal_says_when_the_destination_is_ahead_of_this_clone(repo, outside, private_list, tmp_path):
    # A tip this clone lacks hides what the destination already holds.
    answer(outside, "repo-view", "PRIVATE\n")
    commit(repo, "old.txt", f"written by {NAME}\n", "an old commit")
    assert run("jalon", "push", "origin", "main", cwd=repo).returncode == 0
    other = tmp_path / "other"
    run("git", "clone", "-q", tmp_path / "remote.git", other)
    commit(other, "theirs.txt", "a clean line\n", "their commit")
    assert run("git", "push", "-q", "origin", "main", cwd=other).returncode == 0
    answer(outside, "repo-view", "PUBLIC\n")
    run("git", "checkout", "-q", "-b", "mine", cwd=repo)
    commit(repo, "mine.txt", "a clean line\n", "my commit")
    done = run("jalon", "push", "origin", "mine", cwd=repo)
    assert done.returncode == 1 and "fetch, then push again" in done.stderr


def test_a_git_lfs_pointer_is_refused_before_the_repositorys_hook_runs(repo, private_list):
    # An LFS pointer is clean; its content goes to the LFS server, which this check never reads.
    beside = own_hook(repo, 0)
    before = remote_tip(repo)
    commit(repo, "data.csv", "version https://git-lfs.github.com/spec/v1\noid sha256:" + "a" * 64 + "\nsize 12\n",
           "a dataset")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode == 1 and "Git LFS pointer" in done.stderr
    assert remote_tip(repo) == before and not (beside / "hook-input").exists()


QUOTED = '\n[[rules]]\nid = "quoted-name"\nregex = """Zorb"latt"""\n'


@pytest.mark.parametrize("name, refused", [('Zorb"latt.txt', True), ("plain.txt", False)])
def test_a_name_git_would_quote_is_read_as_it_is_spelled(repo, private_list, tmp_path, name, refused):
    # Git still escapes a quote or a backslash in a name, whatever core.quotePath says.
    private_list.write_text(private_list.read_text() + QUOTED)
    tip = commit(repo, name, "", "an empty file")
    pushed = run("jalon", "push", "origin", "main", cwd=repo)
    export = tmp_path / "export"
    export.mkdir()
    (export / name).write_text("")
    folder = run("jalon", "leak", "dir", export)
    if refused:
        assert pushed.returncode == 1 and "quoted-name" in pushed.stderr
        assert folder.returncode == 1 and "quoted-name" in folder.stderr
    else:
        assert pushed.returncode == 0, pushed.stderr
        assert remote_tip(repo) == [tip] and folder.returncode == 0, folder.stderr


# Texts and folders.

def test_an_issue_body_with_a_listed_name_is_not_filed_on_a_public_repository(outside, body, private_list):
    answer(outside, "repo-view", "PUBLIC\n")
    body.write_text(body.read_text().replace("Because the source says so.", f"Because {NAME} said so."))
    done = run("jalon", "park", "file", "--title", "A title", "--body-file", body, "--depth", "quick")
    assert done.returncode != 0 and "private-name" in done.stderr
    assert calls(outside, "issue create") == []


def test_an_issue_title_with_a_listed_name_is_not_filed_either(outside, body, private_list):
    answer(outside, "repo-view", "PUBLIC\n")
    done = run("jalon", "park", "file", "--title", f"Ask {NAME}", "--body-file", body, "--depth", "quick")
    assert done.returncode != 0
    assert calls(outside, "issue create") == []


def test_without_a_list_no_issue_is_filed_on_a_public_repository(outside, body):
    answer(outside, "repo-view", "PUBLIC\n")
    done = run("jalon", "park", "file", "--title", "A title", "--body-file", body, "--depth", "quick")
    assert done.returncode != 0 and "no private list at" in done.stderr
    assert calls(outside, "issue create") == []


def test_leak_text_passes_a_clean_text_and_refuses_a_listed_name(outside, private_list):
    assert run("jalon", "leak", "text", input="a clean line\n").returncode == 0
    done = run("jalon", "leak", "text", input=f"a line about {NAME}\n")
    assert done.returncode == 1 and "private-name" in done.stderr


def test_leak_dir_passes_a_clean_folder_and_refuses_a_listed_name(outside, alone, private_list):
    (alone / "folder").mkdir()
    (alone / "folder/a.txt").write_text("a clean line\n")
    assert run("jalon", "leak", "dir", "folder").returncode == 0
    (alone / "folder/b.txt").write_text(f"a line about {NAME}\n")
    done = run("jalon", "leak", "dir", "folder")
    assert done.returncode == 1 and "private-name" in done.stderr


@pytest.mark.parametrize("make", ["file in a named folder", "empty named file", "link to a named path"])
def test_leak_dir_reads_names_and_link_targets(outside, alone, private_list, make):
    # The export can name what its contents do not.
    folder = alone / "folder"
    folder.mkdir()
    (folder / "a.txt").write_text("a clean line\n")
    (folder / "clean-link").symlink_to("a.txt")
    assert run("jalon", "leak", "dir", "folder").returncode == 0
    if make == "file in a named folder":
        (folder / NAME).mkdir()
        (folder / NAME / "b.txt").write_text("a clean line\n")
    elif make == "empty named file":
        (folder / f"{NAME}.txt").write_text("")
    else:
        (folder / "link").symlink_to(f"/elsewhere/{NAME}/notes")
    done = run("jalon", "leak", "dir", "folder")
    assert done.returncode == 1 and "private-name" in done.stderr


@pytest.mark.skipif(__import__("os").geteuid() == 0, reason="root reads every file")
def test_leak_dir_refuses_a_file_it_cannot_read(outside, alone, private_list):
    (alone / "folder").mkdir()
    (alone / "folder/a.txt").write_text("a clean line\n")
    (alone / "folder/locked.txt").write_text(f"a line about {NAME}\n")
    (alone / "folder/locked.txt").chmod(0)
    try:
        done = run("jalon", "leak", "dir", "folder")
    finally:
        (alone / "folder/locked.txt").chmod(0o644)
    assert done.returncode == 1 and "cannot read" in done.stderr


def test_leak_dir_refuses_what_is_not_a_file_a_folder_or_a_link(outside, alone, private_list):
    (alone / "folder").mkdir()
    __import__("os").mkfifo(alone / "folder/pipe")
    done = run("jalon", "leak", "dir", "folder")
    assert done.returncode == 1 and "neither a file" in done.stderr


def test_leak_commits_reads_a_range(repo, private_list):
    commit(repo, "second.txt", "a clean line\n", f"as {NAME} asked")
    assert run("jalon", "leak", "commits", "origin/main..HEAD", cwd=repo).returncode == 1
    assert run("jalon", "leak", "commits", "origin/main..origin/main", cwd=repo).returncode == 0
