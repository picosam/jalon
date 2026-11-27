"""park, from inside: the bar, the filing call, the decision record."""

import json
import subprocess
import threading
import time

import pytest

from conftest import BODY
from jalon import leak, park
from jalon.leak import Refused

RECORD = """## Rulings

- 2026-01-02 10:15 UTC: "Yes, the second option."

## Would overturn

A measured cost above the first option's.
"""


@pytest.fixture
def gh(monkeypatch):
    """Replaces the one function that calls gh; returns it, with the calls
    made (`calls`), the text given on standard input (`inputs`), the
    environments of the reads of a decision (`envs`) and the issues it answers
    for (`views`, by number). This checkout's repository is owner/name. Closing an issue runs `on_close` if
    one is set, then closes it as completed at `closed_at`."""
    def fake(*args, input=None, env=None):
        fake.calls.append(list(args))
        fake.inputs.append(input)
        if args[:2] in (("issue", "view"), ("repo", "view")):
            fake.envs.append(env)
        if args[:2] == ("repo", "view"):
            return "https://github.com/owner/name\n"
        if args[:2] == ("issue", "create"):
            return "https://example.org/8\n"
        if args[:2] == ("issue", "close"):
            if fake.on_close:
                fake.on_close()
            fake.views[int(args[2])].update(state="CLOSED", stateReason="COMPLETED", closedAt=fake.closed_at)
            return ""
        return json.dumps(fake.views[int(args[2])])

    fake.calls, fake.inputs, fake.envs, fake.views = [], [], [], {}
    fake.on_close, fake.closed_at = None, "2026-01-03T09:00:00Z"
    decision(fake, 7, title="Which option?")
    monkeypatch.setattr(park, "_gh", fake)
    monkeypatch.setattr(leak, "is_public", lambda target=None: False)
    return fake


def decision(gh, number, **change):
    gh.views[number] = {"number": number, "title": f"Question {number}?", "state": "OPEN", "stateReason": None,
                        "labels": [{"name": "decision"}], "url": f"https://github.com/owner/name/issues/{number}",
                        "closedAt": None,
                        **change}


def test_a_complete_body_passes_the_bar():
    assert park.gaps(BODY) == []


@pytest.mark.parametrize("section", park.SECTIONS)
def test_a_missing_section_is_named(section):
    cut = BODY.replace(f"## {section}\n", "")
    assert any("must be, in order" in gap for gap in park.gaps(cut))


def test_sections_out_of_order_are_refused():
    swapped = BODY.replace("## Assumptions", "## X").replace("## Related items", "## Assumptions").replace("## X", "## Related items")
    assert any("must be, in order" in gap for gap in park.gaps(swapped))


def test_an_empty_section_is_named():
    assert '"Waits on" is empty; write "none"' in park.gaps(BODY.replace("## Waits on\n\nnone", "## Waits on\n"))


def test_done_when_needs_a_list_line():
    assert '"Done when" holds no list line' in park.gaps(BODY.replace("- `true` exits 0.", "It works."))


def test_evidence_opens_with_the_new_code_line():
    assert any("New code" in gap for gap in park.gaps(BODY.replace("New code: none.\n\n", "")))


@pytest.mark.parametrize("fence", ["```\n## Not a section\n```", "~~~\n## Not a section\n~~~",
                                   "````\n```\n## Not a section\n```\n````", "```text\n## Not a section\n`````"])
def test_a_heading_inside_a_code_fence_is_not_a_section(fence):
    # Tildes, longer runs, and an inner fence shorter than its opener.
    fenced = BODY.replace("Checked today: `true`.", fence)
    assert park.gaps(fenced) == []


@pytest.mark.parametrize("done", ["```\n- `true` exits 0.\n```", "~~~\n- `true` exits 0.\n~~~",
                                  "Shown as code:\n\n    - `true` exits 0."])
def test_a_list_line_shown_as_code_is_not_a_list_line(done):
    # The only "item" is an example, not a criterion.
    assert '"Done when" holds no list line' in park.gaps(BODY.replace("- `true` exits 0.", done))


@pytest.mark.parametrize("item", ["+ `true` exits 0.", "1) `true` exits 0.", "1. `true` exits 0.", "* `true` exits 0."])
def test_every_list_marker_counts(item):
    assert park.gaps(BODY.replace("- `true` exits 0.", item)) == []


@pytest.mark.parametrize("line", [
    "New code: none.",
    "New code: none",
    "New code: a folder walk, about 20 lines; looked at gitleaks dir: it skips links; do less: refuse links.",
    "New code: a folder walk,\nabout 20 lines; looked at gitleaks dir: it skips links;\ndo less: refuse links.",
    # Words between the parts are the author's own.
    "New code: the export command, about 90 lines plus tests; looked at git archive (writes a tarball, lists "
    "nothing); do less: export by hand.",
    "New code: one reader of about 60 lines plus tests, which only calls git and tar; looked at "
    "tar alone (keeps no list of what it read); do less: no reader.",
    "New code: one helper of about 45 lines, kept beside the tests; looked at a shell loop over curl "
    "(nothing to resume from); do less: fetch by hand.",
    "New code: none here; each piece names its own.",
    # What follows the line on the next line is evidence, not part of it.
    "New code: none.\nMeasured today: 3 files.",
    "New code: a walk, about 20 lines; looked at x: no; do less: y.\nMeasured today: 3 files.",
])
def test_a_complete_new_code_line_passes(line):
    assert park.gaps(BODY.replace("New code: none.", line)) == []


@pytest.mark.parametrize("line", [
    "New code:", "New code: nonexistent", "New code: a parser.",
    "New code: a parser, about 20 lines; do less: none.",
    "New code: a parser, about some lines; looked at x: no; do less: none.",
    "New code: a parser, about , lines; looked at x: no; do less: none.",
    "New code: a parser, about 20 lines; looked at x: no.",
    "New code: a parser, about 20 lines; looked at; do less: none.",
    "New code: a parser, about 20 lines; looked at x: no; do less: .",
    "New code: about 20 lines; looked at x: no; do less: none.",
    "```\nNew code: none.\n```",
])
def test_an_incomplete_new_code_line_is_named(line):
    # The line approves the code it names, so it names
    # each part (what, a size in lines, what was looked at, the do-less option), outside code.
    assert any("New code" in gap for gap in park.gaps(BODY.replace("New code: none.", line)))


def test_evidence_that_is_only_code_is_refused_before_any_gh_call(gh, body):
    # Evidence that opens with code holds no declaration.
    body.write_text(BODY.replace("New code: none.\n\nChecked today: `true`.", "```\n$ true\n```"))
    with pytest.raises(Refused, match="New code"):
        park.file("A title", body, "quick")
    assert gh.calls == []


def test_file_refuses_under_the_bar_without_calling_gh(gh, body):
    body.write_text(BODY.replace("## Why\n", ""))
    with pytest.raises(Refused, match="under the bar"):
        park.file("A title", body, "quick")
    assert gh.calls == []


def test_file_refuses_an_empty_title(gh, body):
    with pytest.raises(Refused, match="title is empty"):
        park.file("  ", body, "quick")
    assert gh.calls == []


def test_file_makes_one_call_with_every_field(gh, body):
    url = park.file("Which option?", body, "full", decision=True, parked=True, assignee="someone",
                    blocked_by="3", parent="2", repo="owner/name")
    assert url == "https://example.org/8"
    assert gh.calls == [["issue", "create", "--title", "Which option?", "--body-file", "-",
                         "--label", "decision", "--label", "parked", "--label", "full",
                         "--assignee", "someone", "--blocked-by", "3", "--parent", "2", "--repo", "owner/name"]]


def test_file_checks_the_text_when_the_repository_is_public(gh, body, monkeypatch):
    seen = []
    monkeypatch.setattr(leak, "is_public", lambda target=None: True)
    monkeypatch.setattr(leak, "check_text", seen.append)
    park.file("A title", body, "none")
    assert seen == ["A title\n\n" + BODY]


def test_gh_receives_the_body_that_was_checked(gh, body, monkeypatch):
    # An edit of the file after the check does not reach GitHub.
    monkeypatch.setattr(leak, "is_public", lambda target=None: True)
    checked = []

    def check(text):
        checked.append(text)
        body.write_text(BODY.replace("Because", "Since"))
    monkeypatch.setattr(leak, "check_text", check)
    park.file("A title", body, "none")
    assert checked == ["A title\n\n" + BODY] and gh.inputs[-1:] == [BODY]


@pytest.fixture
def checkout(alone):
    """The folder as a git checkout: park close records at its top."""
    subprocess.run(["git", "init", "-q", "-b", "main", alone], check=True)
    return alone


def commit_all(checkout):
    subprocess.run(["git", "add", "decisions"], cwd=checkout, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "records"], cwd=checkout, check=True)


def record(alone, text=RECORD):
    path = alone / "record.md"
    path.write_text(text)
    return path


def rows(checkout):
    return [json.loads(line) for line in (checkout / "decisions/index.jsonl").read_text().splitlines()]


def ruled(gh, number, **change):
    """A decision GitHub shows closed as completed on 2026-01-03."""
    decision(gh, number, **{"state": "CLOSED", "stateReason": "COMPLETED", "closedAt": "2026-01-03T09:00:00Z", **change})


def test_close_records_a_decision_github_shows_closed(gh, checkout):
    ruled(gh, 7, title="Which option?")
    target = park.close(7, record(checkout), "which-option")
    assert target == checkout / "decisions/7-which-option.md"
    text = target.read_text()
    assert text.startswith("# Which option?\n\nDecision 7, closed 2026-01-03. Issue: https://github.com/owner/name/issues/7\n")
    assert '"Yes, the second option."' in text
    assert rows(checkout) == [{"number": 7, "title": "Which option?", "closed": "2026-01-03",
                               "link": "https://github.com/owner/name/issues/7", "file": "7-which-option.md", "replaced_by": None}]
    assert [call[:2] for call in gh.calls] == [["repo", "view"], ["issue", "view"]]


def test_close_refuses_an_open_decision_and_changes_nothing(gh, checkout):
    # The issue is closed on GitHub first: no remote step of ours, so no
    # pending record, no resumed close and no race on GitHub.
    with pytest.raises(Refused, match="not closed as completed on GitHub: close it there first"):
        park.close(7, record(checkout), "which-option")
    assert [call[:2] for call in gh.calls] == [["repo", "view"], ["issue", "view"]] and not (checkout / "decisions").exists()


@pytest.mark.parametrize("change", [{"stateReason": "NOT_PLANNED"}, {"stateReason": "DUPLICATE"},
                                    {"stateReason": None}, {"closedAt": None}])
def test_close_refuses_an_issue_closed_without_a_ruling(gh, checkout, change):
    # A decision dropped on GitHub, or one it gives no date, is not recorded.
    ruled(gh, 7, **change)
    with pytest.raises(Refused, match="not closed as completed"):
        park.close(7, record(checkout), "which-option")
    assert not (checkout / "decisions").exists()


def test_close_refuses_an_issue_that_is_not_a_decision(gh, checkout):
    ruled(gh, 7, labels=[{"name": "quick"}])
    with pytest.raises(Refused, match="label decision"):
        park.close(7, record(checkout), "which-option")
    assert not (checkout / "decisions").exists()


@pytest.mark.parametrize("text, why", [
    ("## Rulings\n\n- He said yes.\n\n## Would overturn\n\nA cost.\n", "dated ruling"),
    ('## Rulings\n\n- 2026-01-02 10:15: yes, unquoted\n\n## Would overturn\n\nA cost.\n', "dated ruling"),
    ('## Rulings\n\n- 2026-01-02: "Yes."\n\n## Would overturn\n\nA cost.\n', "dated ruling"),
    ('## Rulings\n\n- 2026-01-02 10:15: "Yes."\n- 2026-01-03: "And no."\n\n## Would overturn\n\nA cost.\n',
     "dated ruling"),
    ('## Rulings\n\n- 2026-02-30 10:15: "Yes."\n\n## Would overturn\n\nA cost.\n', "dated ruling"),
    ('## Rulings\n\n- 2026-13-02 10:15: "Yes."\n\n## Would overturn\n\nA cost.\n', "dated ruling"),
    ('## Rulings\n\n- 2026-01-02 25:15: "Yes."\n\n## Would overturn\n\nA cost.\n', "dated ruling"),
    ('## Rulings\n\n- 2026-01-02 10:61: "Yes."\n\n## Would overturn\n\nA cost.\n', "dated ruling"),
    ('## Rulings\n\n- 2026-01-02 10:15: "Yes."\n', "Would overturn"),
    ('## Rulings\n\n- 2026-01-02 10:15: "Yes."\n\n## Would overturn\n', "Would overturn"),
])
def test_close_refuses_a_record_without_its_two_parts(gh, checkout, text, why):
    # Every ruling carries its time, and its date and time are real ones.
    ruled(gh, 7)
    with pytest.raises(Refused, match=why):
        park.close(7, record(checkout, text), "which-option")
    assert not any((checkout / "decisions").iterdir())  # read after the leftover check, under the lock


@pytest.mark.parametrize("ruling", ['- 2026-01-02, time unknown: "Yes."',
                                    '- 2024-02-29 23:59 UTC: "A leap day."',
                                    '- 2026-01-02 10:15 UTC, on the first option: "Yes,\n  the second one."'])
def test_a_ruling_may_say_its_time_is_unknown_and_may_wrap(gh, checkout, ruling):
    ruled(gh, 7)
    park.close(7, record(checkout, f"## Rulings\n\n{ruling}\n\n## Would overturn\n\nA cost.\n"), "which-option")
    assert rows(checkout)[0]["number"] == 7


@pytest.mark.parametrize("name", ["Which Option", "which_option", "-x", "x-", ""])
def test_close_refuses_a_name_that_is_not_hyphenated_lower_case(gh, checkout, name):
    ruled(gh, 7)
    with pytest.raises(Refused, match="short name"):
        park.close(7, record(checkout), name)


@pytest.mark.parametrize("left", ["a record", "a line", "both", "a part file"])
def test_close_refuses_and_names_what_the_decision_already_has(gh, checkout, left):
    # A run that stopped part-way left a record, a
    # line or both; any run for that decision, the same command again included, names what
    # it found and changes no file. A person reconciles it with git.
    ruled(gh, 7)
    if left == "a part file":  # stopped while writing the record
        (checkout / "decisions").mkdir()
        (checkout / "decisions/.7-which-option.md.part").write_text("half a record")
    else:
        park.close(7, record(checkout), "which-option")
    if left == "a record":
        (checkout / "decisions/index.jsonl").write_text("")
    elif left == "a line":
        (checkout / "decisions/7-which-option.md").unlink()
    before = {path: path.read_bytes() for path in (checkout / "decisions").iterdir()}
    found = {"a record": "7-which-option.md in", "a line": "its line in index.jsonl in",
             "both": "7-which-option.md, its line in index.jsonl in", "a part file": ".7-which-option.md.part in"}[left]
    gone = record(checkout)
    gone.unlink()  # with the draft gone, the leftover is still what is named
    for name in ("which-option", "another-name"):
        with pytest.raises(Refused, match=f"#7 already has {found} .*reconcile it with git"):
            park.close(7, gone, name)
    assert {path: path.read_bytes() for path in (checkout / "decisions").iterdir()} == before


def test_a_replaced_decision_loses_its_file_and_keeps_its_line(gh, checkout):
    ruled(gh, 7)
    park.close(7, record(checkout), "which-option")
    commit_all(checkout)
    ruled(gh, 9, title="Which option, again?")
    new = park.close(9, record(checkout), "which-option-again", replaces=7)
    assert not (checkout / "decisions/7-which-option.md").exists()
    assert "Replaces decision 7." in new.read_text()
    assert [(row["number"], row["replaced_by"]) for row in rows(checkout)] == [(7, 9), (9, None)]


@pytest.mark.parametrize("state", ["never committed", "changed since", "changed and staged"])
def test_a_decision_not_committed_as_it_stands_cannot_be_replaced(gh, checkout, state):
    # Its file goes, so git must hold its words first: git removes it, and
    # refuses one it does not track or that differs from the last commit.
    ruled(gh, 7)
    old = park.close(7, record(checkout), "which-option")
    if state != "never committed":
        commit_all(checkout)
        old.write_text(old.read_text() + "An amendment.\n")
    if state == "changed and staged":
        subprocess.run(["git", "add", "decisions/7-which-option.md"], cwd=checkout, check=True)
    words = old.read_bytes()
    ruled(gh, 9)
    with pytest.raises(Refused, match="git did not remove the record of #7"):
        park.close(9, record(checkout), "which-option-again", replaces=7)
    assert old.read_bytes() == words and not (checkout / "decisions/9-which-option-again.md").exists()
    assert [row["number"] for row in rows(checkout)] == [7]


def test_a_decision_already_replaced_cannot_be_replaced_again(gh, checkout):
    # The chain 7 -> 9 stays; 9, still active, is what 11 replaces.
    ruled(gh, 7)
    park.close(7, record(checkout), "which-option")
    commit_all(checkout)
    ruled(gh, 9)
    park.close(9, record(checkout), "which-option-again", replaces=7)
    commit_all(checkout)
    ruled(gh, 11)
    with pytest.raises(Refused, match="already replaced by #9"):
        park.close(11, record(checkout), "which-option-last", replaces=7)
    park.close(11, record(checkout), "which-option-last", replaces=9)
    assert [(row["number"], row["replaced_by"]) for row in rows(checkout)] == [(7, 9), (9, 11), (11, None)]


def test_close_refuses_to_replace_a_decision_the_index_does_not_hold(gh, checkout):
    ruled(gh, 7)
    with pytest.raises(Refused, match="#5 is not in"):
        park.close(7, record(checkout), "which-option", replaces=5)
    assert not (checkout / "decisions/7-which-option.md").exists()


def test_the_record_lands_at_the_top_of_the_checkout(gh, checkout, monkeypatch):
    # Run from a subfolder, the record is still the repository's.
    ruled(gh, 7)
    (checkout / "sub").mkdir()
    monkeypatch.chdir(checkout / "sub")
    target = park.close(7, record(checkout), "which-option")
    assert target == checkout / "decisions/7-which-option.md" and not (checkout / "sub/decisions").exists()


def test_close_outside_a_checkout_refuses_before_any_gh_call(gh, alone):
    with pytest.raises(Refused, match="inside the repository"):
        park.close(7, record(alone), "which-option")
    assert gh.calls == []


@pytest.mark.parametrize("second", [9, 7])
def test_two_closes_at_once_keep_one_line_each(gh, checkout, monkeypatch, second):
    # The second waits for the first, then reads the line it wrote;
    # for the same decision, it finds that line and refuses.
    ruled(gh, 7)
    ruled(gh, 9)
    real = park._index
    started, outcome = [], []

    def other():
        try:
            park.close(second, record(checkout), "other-option")
            outcome.append("recorded")
        except Refused as refusal:
            outcome.append(str(refusal))

    def slow(root):
        lines = real(root)
        if not started:
            started.append(threading.Thread(target=other))
            started[0].start()
            time.sleep(0.5)
        return lines
    monkeypatch.setattr(park, "_index", slow)
    park.close(7, record(checkout), "which-option")
    started[0].join(10)
    if second == 9:
        assert outcome == ["recorded"] and sorted(row["number"] for row in rows(checkout)) == [7, 9]
    else:
        assert "#7 already has 7-which-option.md" in outcome[0] and [row["number"] for row in rows(checkout)] == [7]
        assert not (checkout / "decisions/7-other-option.md").exists()


@pytest.mark.parametrize("url", ["https://github.com/owner/other/issues/9", "https://github.com/owner/name/issues/90",
                                 "https://github.com/xowner/name/issues/9"])
def test_close_reads_the_issue_from_this_repository_and_refuses_another(gh, checkout, monkeypatch, url):
    # One repository throughout, GH_REPO left out: the read names
    # it, and the answer must be exactly its issue (not issue 90 for 9).
    monkeypatch.setenv("GH_REPO", "owner/other")
    ruled(gh, 7)
    park.close(7, record(checkout), "which-option")
    assert ["issue", "view", "7", "--repo", "https://github.com/owner/name"] == gh.calls[1][:5]
    assert gh.envs and all(env is not None and "GH_REPO" not in env for env in gh.envs)
    ruled(gh, 9, url=url)
    with pytest.raises(Refused, match="not an issue of https://github.com/owner/name"):
        park.close(9, record(checkout), "other-option")
    assert [row["number"] for row in rows(checkout)] == [7]


def test_close_records_only_in_the_repository_the_issue_was_closed_in(gh, checkout):
    # The hand close and the record name one repository, "$repo"; if gh's
    # default moved between them, the record refuses before reading the issue.
    ruled(gh, 7)
    with pytest.raises(Refused, match="closed in owner/other, but this checkout's repository is https://github.com/owner/name"):
        park.close(7, record(checkout), "which-option", repo="owner/other")
    assert [call[:2] for call in gh.calls] == [["repo", "view"]] and not (checkout / "decisions").exists()
    park.close(7, record(checkout), "which-option", repo="https://github.com/owner/name")
    assert [row["link"] for row in rows(checkout)] == ["https://github.com/owner/name/issues/7"]


def test_close_refuses_a_folder_holding_another_repositorys_decisions(gh, checkout):
    # A fork whose gh points elsewhere would retire another repository's record.
    ruled(gh, 7)
    park.close(7, record(checkout), "which-option")
    index = checkout / "decisions/index.jsonl"
    index.write_text(index.read_text().replace("owner/name", "upstream/name"))
    ruled(gh, 9)
    with pytest.raises(Refused, match="records decisions of another repository"):
        park.close(9, record(checkout), "other-option", replaces=7)
    assert (checkout / "decisions/7-which-option.md").exists()


@pytest.mark.parametrize("evidence", ["```\n$ wc -l park.py\n```\n\nNew code: none.", "    New code: none."])
def test_a_declaration_after_or_inside_code_is_not_one(gh, body, evidence):
    # The opening of Evidence is prose, or there is no declaration.
    body.write_text(BODY.replace("New code: none.", evidence))
    with pytest.raises(Refused, match="New code"):
        park.file("A title", body, "quick")
    assert gh.calls == []


def test_a_size_needs_a_real_number():
    line = "New code: a parser, about 1,,, lines; looked at x: no; do less: none."
    assert any("New code" in gap for gap in park.gaps(BODY.replace("New code: none.", line)))
