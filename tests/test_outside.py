"""From outside: the real command, run in a scratch repository with a
stand-in gh. One test for each command's main path, and one for each refusal
that guards the boundary no private thing may cross.

Nothing here imports the tool. gitleaks and git are the real ones.
"""

import base64
import io
import json
import shutil
import zipfile

import pytest

from conftest import LIST, run

pytestmark = pytest.mark.skipif(shutil.which("gitleaks") is None, reason="these tests run the real gitleaks")

NAME = "Zorblatt"  # the one name on the test list


def answer(standin, key, out="", code=0):
    (standin / f"{key}.out").write_text(out)
    (standin / f"{key}.exit").write_text(str(code))


def calls(standin, key):
    return [line for line in (standin / "calls").read_text().splitlines() if line.startswith(key)]


@pytest.fixture
def repo(alone, outside, tmp_path):
    """A clone with one pushed commit and a bare remote GitHub calls public,
    named as an address: only an address is asked of GitHub."""
    remote = tmp_path / "remote.git"
    run("git", "init", "-q", "--bare", "-b", "main", remote)
    run("git", "init", "-q", "-b", "main", alone)
    run("git", "remote", "add", "origin", remote.as_uri(), cwd=alone)
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
    answer(outside, "repo-url", "https://github.com/owner/name\n")
    answer(outside, "repo-view", "PRIVATE\n")
    answer(outside, "issue-create", "https://example.org/8\n")
    done = run("jalon", "park", "file", "--title", "A title", "--body-file", body, "--depth", "quick", "--decision")
    assert (done.returncode, done.stdout) == (0, "https://example.org/8\n")
    assert calls(outside, "issue create") == ["issue create --title A title --body-file - --label decision --label quick "
                                              "--repo https://github.com/owner/name"]
    assert (outside / "stdin").read_text() == body.read_text()
    # The checkout's repository, the visibility read and the filing, and no lookup of open issues.
    assert [line.split(" --")[0] for line in calls(outside, "")] == [
        "repo view", "repo view https://github.com/owner/name", "issue create"]


def test_park_file_files_into_the_checkouts_repository_on_its_own_host(outside, body):
    # The checkout's remote is on another host than github.com, and GH_REPO
    # names another repository: the checkout's is read with GH_REPO left out,
    # and the visibility read and the filing both name it, host included.
    answer(outside, "repo-url", "https://git.example.org/owner/name\n")
    answer(outside, "repo-view", "PRIVATE\n")
    answer(outside, "issue-create", "https://git.example.org/owner/name/issues/8\n")
    done = run("jalon", "park", "file", "--title", "A title", "--body-file", body, "--depth", "quick",
               env={"GH_REPO": "owner/other"})
    assert (done.returncode, done.stdout) == (0, "https://git.example.org/owner/name/issues/8\n"), done.stderr
    assert [line.removesuffix(" GH_REPO=owner/other") for line in calls(outside, "")] == [
        "repo view --json url --jq .url",
        "repo view https://git.example.org/owner/name --json visibility --jq .visibility",
        "issue create --title A title --body-file - --label quick --repo https://git.example.org/owner/name"]
    assert "GH_REPO" not in calls(outside, "")[0]


def test_park_takes_no_deposit(outside, body, alone):
    # A deposit is filed as any issue is, then deleted with rm: park has no
    # option and no command for it.
    (alone / "deposit.md").write_text("a proposal")
    done = run("jalon", "park", "file", "--title", "A title", "--body-file", body, "--depth", "quick",
               "--deposit", "deposit.md")
    assert done.returncode == 2 and (alone / "deposit.md").exists() and calls(outside, "") == []
    done = run("jalon", "park", "reject", "deposit.md", "--reason", "covered by #3")
    assert done.returncode == 2 and (alone / "deposit.md").exists()
    listed = run("jalon", "park", "--help").stdout
    assert "file" in listed and "close" in listed and "reject" not in listed


def decision(outside, alone, state="CLOSED"):
    """Issue 7, a decision GitHub shows closed as completed (or open), in a
    checkout of a private repository."""
    run("git", "init", "-q", "-b", "main", alone)
    answer(outside, "repo-view", "PRIVATE\n")
    answer(outside, "repo-url", "https://github.com/owner/name\n")
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
    assert done.returncode == 1 and "this checkout's repository is https://github.com/owner/name" in done.stderr
    assert calls(outside, "issue view") == [] and not (alone / "decisions").exists()
    done = run("jalon", "park", "close", "7", "--record-file", "record.md", "--name", "which-option",
               env={"GH_REPO": "owner/other"})
    assert done.returncode == 0, done.stderr
    assert calls(outside, "") and not [line for line in calls(outside, "") if "GH_REPO=" in line]
    assert calls(outside, "issue view")[0].startswith("issue view 7 --repo https://github.com/owner/name ")


def files_under(folder):
    """Every file of the checkout, and git's index among them."""
    return {path: path.read_bytes() for path in folder.rglob("*")
            if path.is_file() and (".git" not in path.parts or path.name == "index")}


@pytest.mark.parametrize("case", ["committed", "modified", "staged", "untracked", "row names ../keep.md",
                                  "row names 8-other.md"])
def test_park_close_leaves_the_replaced_records_deletion_to_git(outside, alone, case):
    # git removes the record of decision 7, found by its number, or refuses
    # and nothing changes. What the index row names is never a path to delete.
    decision(outside, alone)
    assert run("jalon", "park", "close", "7", "--record-file", "record.md", "--name", "which-option").returncode == 0
    (alone / "keep.md").write_text("kept\n")
    (alone / "decisions/8-other.md").write_text("kept\n")
    old, index = alone / "decisions/7-which-option.md", alone / "decisions/index.jsonl"
    if case.startswith("row names"):
        index.write_text(index.read_text().replace('"7-which-option.md"', json.dumps(case.split()[-1])))
    run("git", "add", "keep.md", "decisions/8-other.md", "decisions/index.jsonl", cwd=alone)
    if case != "untracked":
        run("git", "add", "decisions/7-which-option.md", cwd=alone)
    assert run("git", "commit", "-q", "-m", "records", cwd=alone).returncode == 0
    if case in ("modified", "staged"):
        old.write_text(old.read_text() + "An amendment.\n")
    if case == "staged":
        run("git", "add", "decisions/7-which-option.md", cwd=alone)
    answer(outside, "issue-view", json.dumps({"number": 9, "title": "Which option, again?", "state": "CLOSED",
                                              "stateReason": "COMPLETED", "closedAt": "2026-01-04T09:00:00Z",
                                              "labels": [{"name": "decision"}],
                                              "url": "https://github.com/owner/name/issues/9"}))
    before = files_under(alone)
    done = run("jalon", "park", "close", "9", "--record-file", "record.md", "--name", "which-option-again",
               "--replaces", "7")
    if case in ("modified", "staged", "untracked"):
        assert done.returncode == 1 and "git did not remove the record of #7" in done.stderr
        assert files_under(alone) == before
    else:
        assert done.returncode == 0, done.stderr
        assert not old.exists() and (alone / "decisions/9-which-option-again.md").exists()
        assert "rm 'decisions/7-which-option.md'" in done.stderr  # git's own line says what went
        assert run("git", "status", "--short", "decisions/7-which-option.md", cwd=alone).stdout[:2] == "D "
        for kept in ("keep.md", "decisions/8-other.md"):
            assert (alone / kept).read_bytes() == b"kept\n"


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


@pytest.mark.parametrize("listed", [False, True])
def test_a_destination_not_written_as_an_address_is_scanned_without_asking(repo, outside, private_list, listed):
    # gh would read team/records as a repository on GitHub, and call it private; git reads a folder of the clone.
    answer(outside, "repo-view", "PRIVATE\n")
    run("git", "init", "-q", "--bare", "-b", "main", repo / "team/records")
    run("git", "remote", "set-url", "origin", "team/records", cwd=repo)
    assert run("git", "push", "-q", "origin", "main", cwd=repo).returncode == 0
    before = remote_tip(repo)
    tip = commit(repo, "second.txt", f"written by {NAME if listed else 'someone'}\n", "the second commit")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    if listed:
        assert done.returncode == 1 and "private-name" in done.stderr
        assert remote_tip(repo) == before
    else:
        assert done.returncode == 0, done.stderr
        assert remote_tip(repo) == [tip]
    assert calls(outside, "repo view") == []


@pytest.mark.parametrize("other", ["other.git", "team/records "])
@pytest.mark.parametrize("listed", [False, True])
def test_an_address_git_would_read_as_another_holds_nothing(repo, private_list, listed, other):
    # The destination is the folder team/records. A remote of that very name leads elsewhere, to a
    # repository that holds the commit being pushed: asked by its address, git would list that one.
    # Elsewhere may differ from the address by one trailing space.
    for bare in ("team/records", other):
        run("git", "init", "-q", "--bare", "-b", "main", repo / bare)
    run("git", "remote", "set-url", "origin", "team/records", cwd=repo)
    assert run("git", "push", "-q", "origin", "main", cwd=repo).returncode == 0
    before = remote_tip(repo)
    tip = commit(repo, "second.txt", f"written by {NAME if listed else 'someone'}\n", "the second commit")
    run("git", "remote", "add", "team/records", other, cwd=repo)
    assert run("git", "push", "-q", "team/records", "main", cwd=repo).returncode == 0
    done = run("jalon", "push", "origin", "main", cwd=repo)
    if listed:
        assert done.returncode == 1 and "private-name" in done.stderr
        assert remote_tip(repo) == before
    else:
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


@pytest.mark.parametrize("listed", [False, True])
def test_the_hook_runs_the_jalon_that_wrote_it(repo, private_list, listed):
    # git runs the hook at the top of the repository being pushed. A jalon.py
    # there would stand in for the check in a Python that looks for modules in
    # the folder it runs in, or in the folders PYTHONPATH names.
    commit(repo, "jalon.py", 'open("../stood-in", "w").close()\n', "a module of the same name")
    tip = commit(repo, "second.txt", f"written by {NAME if listed else 'someone'}\n", "the second commit")
    before = remote_tip(repo)
    done = run("jalon", "push", "origin", "main", cwd=repo, env={"PYTHONPATH": "."})
    if listed:
        assert done.returncode == 1 and "private-name" in done.stderr
        assert remote_tip(repo) == before
    else:
        assert done.returncode == 0, done.stderr
        assert remote_tip(repo) == [tip]
    assert not (repo.parent / "stood-in").exists()


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


@pytest.mark.parametrize("name, refused", [("for\u00a0someone", False), (f"for\u00a0{NAME}", True),
                                           ("for\u2028someone", False), (f"for\u2028{NAME}", True)])
def test_a_branch_name_with_another_space_or_line_break_is_read_whole(repo, private_list, name, refused):
    # git allows a no-break space and U+2028 in a branch name; the hook's input is split at spaces and line
    # feeds only.
    tip = commit(repo, "second.txt", "a clean line\n", "the second commit")
    run("git", "branch", name, cwd=repo)
    done = run("jalon", "push", "origin", name, cwd=repo)
    if refused:
        assert done.returncode == 1 and "private-name" in done.stderr
        assert remote_tip(repo, f"refs/heads/{name}") == []
    else:
        assert done.returncode == 0, done.stderr
        assert remote_tip(repo, f"refs/heads/{name}") == [tip]


def test_a_source_written_with_spaces_is_read_from_the_right(repo, private_list):
    # git hands the hook the source as it was written, and a revision may hold spaces.
    tip = commit(repo, "second.txt", "a clean line\n", "the second commit")
    done = run("jalon", "push", "origin", "HEAD^{/the second commit}:refs/heads/other", cwd=repo)
    assert done.returncode == 0, done.stderr
    assert remote_tip(repo, "refs/heads/other") == [tip]


def test_a_ref_at_the_destination_passes_no_commit_off_as_held(repo, private_list, tmp_path):
    # What the destination lists is read at line feeds only: a ref there whose name holds U+2028 and then
    # a commit's id is one line, not a second one that names that commit as held.
    tip = commit(repo, "second.txt", f"written by {NAME}\n", "the second commit")
    before = remote_tip(repo)
    assert run("git", "--git-dir", tmp_path / "remote.git", "branch", f"a {tip}", "main").returncode == 0
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode == 1 and "private-name" in done.stderr
    assert remote_tip(repo) == before


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


@pytest.mark.parametrize("resolution, refused", [("a resolved line\n", False), (f"resolved by {NAME}\n", True)])
def test_a_merge_of_three_parents_is_read_for_what_it_adds(repo, private_list, resolution, refused):
    # The three parents are clean; the merge commit itself adds a file.
    for side in ("one", "two"):
        run("git", "checkout", "-q", "-b", side, "main", cwd=repo)
        commit(repo, f"{side}.txt", "a clean line\n", side)
    run("git", "checkout", "-q", "main", cwd=repo)
    commit(repo, "main.txt", "a clean line\n", "main's own")
    assert run("git", "merge", "-q", "--no-commit", "one", "two", cwd=repo).returncode == 0
    tip = commit(repo, "merged.txt", resolution, "merged")
    assert len(run("git", "rev-parse", "HEAD^@", cwd=repo).stdout.split()) == 3
    done = run("jalon", "push", "origin", "main", cwd=repo)
    if refused:
        assert done.returncode == 1 and "private-name" in done.stderr
    else:
        assert done.returncode == 0, done.stderr
        assert remote_tip(repo) == [tip]


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


def test_a_refusal_comes_before_the_repositorys_own_hook_runs(repo, private_list):
    # The repository's hook may send content elsewhere, as Git LFS's does: it does not run on a refused push.
    beside = own_hook(repo, 0)
    before = remote_tip(repo)
    commit(repo, "data.csv", f"written by {NAME}\n", "a dataset")
    done = run("jalon", "push", "origin", "main", cwd=repo)
    assert done.returncode == 1 and "private-name" in done.stderr
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
    answer(outside, "repo-url", "https://github.com/owner/name\n")
    answer(outside, "repo-view", "PUBLIC\n")
    body.write_text(body.read_text().replace("Because the source says so.", f"Because {NAME} said so."))
    done = run("jalon", "park", "file", "--title", "A title", "--body-file", body, "--depth", "quick")
    assert done.returncode != 0 and "private-name" in done.stderr
    assert calls(outside, "issue create") == []


def test_an_issue_title_with_a_listed_name_is_not_filed_either(outside, body, private_list):
    answer(outside, "repo-url", "https://github.com/owner/name\n")
    answer(outside, "repo-view", "PUBLIC\n")
    done = run("jalon", "park", "file", "--title", f"Ask {NAME}", "--body-file", body, "--depth", "quick")
    assert done.returncode != 0
    assert calls(outside, "issue create") == []


def test_without_a_list_no_issue_is_filed_on_a_public_repository(outside, body):
    answer(outside, "repo-url", "https://github.com/owner/name\n")
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


# A ZIP made by `zip -P`, whose one member holds the listed name.
LOCKED = base64.b64decode(
    "UEsDBAoACQAAAKRde12KFpe4IgAAABYAAAAJABwAbm90ZXMudHh0VVQJAANDbQlrQ20Ja3V4CwABBPUBAAAEAAAAAFUWBvfGROZbKJGlxAzJTREFtpD9"
    "U3J3udP9z7IGqvFBXT5QSwcIihaXuCIAAAAWAAAAUEsBAh4DCgAJAAAApF17XYoWl7giAAAAFgAAAAkAGAAAAAAAAQAAAKSBAAAAAG5vdGVzLnR4dFVU"
    "BQADQ20Ja3V4CwABBPUBAAAEAAAAAFBLBQYAAAAAAQABAE8AAAB1AAAAAAA=")


def not_text(folder):
    """A ZIP whose text holds the listed name, an image and an encrypted ZIP:
    none is text, and none is opened. Returns their names."""
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("notes.txt", f"a line about {NAME}\n" * 50)
    (folder / "export.zip").write_bytes(packed.getvalue())
    (folder / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    (folder / "locked.zip").write_bytes(LOCKED)
    return ["export.zip", "locked.zip", "photo.png"]


@pytest.mark.parametrize("listed", [False, True])
def test_what_is_not_text_is_named_and_does_not_decide(repo, private_list, tmp_path, listed):
    # In a folder and in a pushed range: the three are named as not read, and
    # the exit code is the one the text beside them earns.
    folder = tmp_path / "export"
    folder.mkdir()
    for where in (folder, repo):
        names = not_text(where)
        (where / "  spaced.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(255, -1, -1)))
        names.append("  spaced.png")  # named with its two spaces, in a push as in a folder
        (where / "notes.txt").write_text(f"written by {NAME if listed else 'someone'}\n")
    run("git", "add", "notes.txt", *names, cwd=repo)
    assert run("git", "commit", "-q", "-m", "an export", cwd=repo).returncode == 0
    for done in (run("jalon", "leak", "dir", folder), run("jalon", "push", "origin", "main", cwd=repo)):
        assert done.returncode == (1 if listed else 0), done.stderr
        assert ("private-name" in done.stderr) is listed
        for name in names:
            assert f"jalon: not read, as it is not text: {name!r}" in done.stderr


def test_no_folder_above_the_copy_sets_a_text_aside(outside, alone, private_list, tmp_path):
    # gitleaks' own rules skip what lies under such a folder; the copy it reads may be made in one.
    (alone / "folder").mkdir()
    (alone / "folder/a.txt").write_text(f"a line about {NAME}\n")
    (tmp_path / "node_modules").mkdir()
    done = run("jalon", "leak", "dir", "folder", env={"TMPDIR": str(tmp_path / "node_modules")})
    assert done.returncode == 1 and "private-name" in done.stderr and "file 0 is 'a.txt'" in done.stderr


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


# status: the two posts, and the refusals that keep a pull request from choosing what judges it.

DECLARED = '[tests]\nplace = "here"\ncommands = ["touch ran-1", "true"]\n'
STATUSES = "api repos/owner/name/statuses/"


def pull(outside, repo, title="A clean title", state="OPEN", head=None, declared=DECLARED):
    """Pull request 5 of owner/name, at `head` (the checkout's HEAD unless
    given), with `declared` as the default branch's jalon.toml (None: it has
    none)."""
    head = head or run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    answer(outside, "repo-url", "https://github.com/owner/name\n")
    answer(outside, "pr-view", json.dumps({"state": state, "headRefOid": head, "title": title}))
    answer(outside, "api-contents", *(('{"message":"Not Found"}', 1) if declared is None else (declared,)))
    return head


def test_status_tests_runs_the_declared_commands_here_and_posts_success(repo, outside, private_list):
    head = pull(outside, repo)
    done = run("jalon", "status", "tests", "5", cwd=repo)
    assert done.returncode == 0, done.stderr
    assert (repo / "ran-1").exists()
    assert calls(outside, STATUSES) == [
        f"{STATUSES}{head} --hostname github.com -f state=success -f context=jalon/tests "
        f"-f description=2 commands passed at {head[:7]}; run here by jalon status tests"]
    # Read with no ref: GitHub answers with the default branch's file.
    assert calls(outside, "api repos/owner/name/contents/") == [
        "api repos/owner/name/contents/jalon.toml --hostname github.com -H Accept: application/vnd.github.raw+json"]


def test_status_tests_posts_failure_at_the_first_command_that_fails(repo, outside, private_list):
    head = pull(outside, repo, declared='[tests]\nplace = "here"\ncommands = ["true", "exit 3", "touch never"]\n')
    done = run("jalon", "status", "tests", "5", cwd=repo)
    assert done.returncode == 1 and not (repo / "never").exists()
    assert calls(outside, STATUSES) == [
        f"{STATUSES}{head} --hostname github.com -f state=failure -f context=jalon/tests "
        f"-f description=Command 2 of 3 exited 3 at {head[:7]}; run here by jalon status tests"]


@pytest.mark.parametrize("case, said", [
    ("merged", "is merged, not open"),
    ("elsewhere", "not at pull request 5's head"),
    ("changed", "git status shows changes"),
    ("untracked", "git status shows changes"),
])
def test_status_tests_refuses_a_checkout_that_is_not_the_head_and_posts_nothing(repo, outside, private_list,
                                                                               case, said):
    first = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    if case == "elsewhere":
        commit(repo, "second.txt", "a clean line\n", "the second commit")
    pull(outside, repo, state="MERGED" if case == "merged" else "OPEN", head=first)
    if case == "changed":
        (repo / "first.txt").write_text("a changed line\n")
    if case == "untracked":
        (repo / "new.txt").write_text("a clean line\n")
    done = run("jalon", "status", "tests", "5", cwd=repo)
    assert done.returncode == 1 and said in done.stderr
    assert calls(outside, STATUSES) == [] and not (repo / "ran-1").exists()


@pytest.mark.parametrize("declared", [None, '[tests]\nplace = "github"\ncommands = ["touch ran-1"]\n'])
def test_status_tests_runs_nothing_without_a_declaration_it_can_run_on_the_default_branch(repo, outside, private_list,
                                                                                         declared):
    pull(outside, repo, declared=declared)
    done = run("jalon", "status", "tests", "5", cwd=repo)
    assert done.returncode == 1 and calls(outside, STATUSES) == [] and not (repo / "ran-1").exists()


def test_status_tests_runs_the_default_branchs_commands_not_the_pull_requests(repo, outside, private_list):
    commit(repo, "jalon.toml", '[tests]\nplace = "here"\ncommands = ["touch ran-by-the-pull-request"]\n', "declare")
    pull(outside, repo, declared='[tests]\nplace = "here"\ncommands = ["touch ran-by-the-default-branch"]\n')
    done = run("jalon", "status", "tests", "5", cwd=repo)
    assert done.returncode == 0, done.stderr
    assert (repo / "ran-by-the-default-branch").exists() and not (repo / "ran-by-the-pull-request").exists()


def test_status_title_posts_success_for_a_title_the_list_passes(repo, outside, private_list):
    head = pull(outside, repo)
    done = run("jalon", "status", "title", "5", cwd=repo)
    assert done.returncode == 0, done.stderr
    assert calls(outside, STATUSES) == [
        f"{STATUSES}{head} --hostname github.com -f state=success -f context=jalon/title "
        "-f description=The title passes the private list; posted by jalon status title"]


def test_status_title_posts_failure_for_a_title_with_a_listed_name(repo, outside, private_list):
    head = pull(outside, repo, title=f"Ask {NAME} first")
    done = run("jalon", "status", "title", "5", cwd=repo)
    assert done.returncode == 1 and "private-name" in done.stderr
    assert calls(outside, STATUSES) == [
        f"{STATUSES}{head} --hostname github.com -f state=failure -f context=jalon/title "
        "-f description=The title does not pass the private list; posted by jalon status title"]


def test_status_title_posts_nothing_on_a_private_repository(repo, outside, private_list):
    pull(outside, repo, title=f"Ask {NAME} first")
    answer(outside, "repo-view", "PRIVATE\n")
    done = run("jalon", "status", "title", "5", cwd=repo)
    assert done.returncode == 1 and "checks nothing yet" in done.stderr and calls(outside, STATUSES) == []


def test_a_description_the_list_refuses_is_not_posted(repo, outside, private_list):
    private_list.write_text(LIST + "\n[[rules]]\nid = \"a-phrase\"\ndescription = \"a listed phrase\"\n"
                                   "regex = '''posted by jalon'''\n")
    pull(outside, repo)
    done = run("jalon", "status", "title", "5", cwd=repo)
    assert done.returncode == 1 and "a-phrase" in done.stderr and calls(outside, STATUSES) == []
