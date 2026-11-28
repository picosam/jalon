"""commit, from inside: the vocabulary a [commits] table declares, the subject git takes, and how one is judged."""

import re

import pytest

from jalon import commit
from jalon.leak import Refused

DEFAULT = commit.rules({})


@pytest.mark.parametrize("subject", [
    "change: check commit subjects",
    "fix!: a breaking fix",
    'Revert "change: check commit subjects"',
    'Reapply "Revert \\"change: x\\""',
])
def test_a_subject_in_the_grammar_with_a_declared_type_passes(subject):
    assert commit.judge(subject, DEFAULT) is None


@pytest.mark.parametrize("subject, said", [
    ("", "the subject is empty"),
    ("Check commit subjects", "does not read"),
    ("change:no space", "does not read"),
    ("change: ", "does not read"),
    ("Change: capitalised", "does not read"),
    ("feat: x", "the type 'feat' is not declared"),
    ("change(leak): x", "the scope 'leak' is not declared"),
])
def test_a_subject_outside_the_vocabulary_is_refused(subject, said):
    assert said in commit.judge(subject, DEFAULT)


def test_a_declared_scope_passes_and_a_retired_name_gives_its_redirect():
    rules = commit.rules({"scopes": ["leak", "push-path"], "retired": {"plan": "design", "tools": "leak"}})
    assert commit.judge("change(push-path): x", rules) is None
    assert commit.judge("plan: x", rules) == "the type 'plan' is retired; use design"
    assert commit.judge("fix(tools): x", rules) == "the scope 'tools' is retired; use leak"


def test_the_eleven_types_are_the_default_and_a_list_replaces_them_wholly():
    assert DEFAULT["types"] == {"change", "fix", "refactor", "guard", "test", "document", "design", "record",
                                "deliver", "maintain", "revert"}
    assert "not declared" in commit.judge("feat: x", DEFAULT)
    rules = commit.rules({"types": ["feat"]})
    assert commit.judge("feat: x", rules) is None
    assert "not declared" in commit.judge("change: x", rules)
    assert "needs `revert`" in commit.judge('Revert "feat: x"', rules)


@pytest.mark.parametrize("table, said", [
    ("[]", "is not a table"),
    ({"select": []}, "'select'"),
    ({"types": "change"}, "types must be a list"),
    ({"types": ["Change"]}, "types must be a list"),
    ({"types": ["re-vert"]}, "types must be a list"),
    ({"scopes": ["a b"]}, "scopes must be a list"),
    ({"scopes": ["fix"]}, "'fix' both as a type and as a scope"),
    ({"retired": ["plan"]}, "retired must be a table"),
    ({"retired": {"fix": "change"}}, "retires 'fix', which it also declares"),
    ({"retired": {"plan": 1}}, "not text"),
    ({"retired": {"plan": " "}}, "not text"),
    ({"data": "records"}, "data must be a list"),
    ({"data": ["/records"]}, "data must be a list"),
    ({"data": ["records/../src"]}, "data must be a list"),
    ({"data": ["./records"]}, "data must be a list"),
    ({"data": [""]}, "data must be a list"),
])
def test_a_table_it_cannot_read_is_refused_naming_the_problem(table, said):
    with pytest.raises(Refused, match=re.escape(said)):
        commit.rules(table)


def test_a_data_folder_is_kept_with_or_without_its_final_slash_and_keeps_its_spaces():
    assert commit.rules({"data": ["records/", "watch", "notes "]})["data"] == [b"records", b"watch", b"notes "]


def test_a_declaration_without_commits_declares_nothing():
    assert commit.declared('[tests]\nplace = "here"\n', "here") is None
    assert commit.declared("[commits]\n", "here")["types"] == DEFAULT["types"]
    with pytest.raises(Refused, match="is not TOML"):
        commit.declared("[commits\n", "here")


@pytest.mark.parametrize("message, subject", [
    (b"change: x\n\nThe body.\n", "change: x"),
    (b"# a comment\nchange: x\n", "change: x"),
    (b"\n\nchange: a subject\nwritten on two lines\n\nThe body.\n", "change: a subject written on two lines"),
    (b"change: x   \n# Please enter the commit message\n", "change: x"),
])
def test_the_subject_is_the_first_paragraph_git_keeps(message, subject):
    assert commit.subject_of(message) == subject
