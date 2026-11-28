"""status, from inside: the declaration's [tests] table it can run, and what it refuses."""

import re

import pytest

from jalon import status
from jalon.leak import Refused


def test_a_declaration_gives_its_commands_in_order():
    text = '[tests]\nplace = "here"\ncommands = ["first", "second"]\n'
    assert status.declared_tests(text) == ["first", "second"]


@pytest.mark.parametrize("text, said", [
    ('place = "here"\n', "no [tests] table"),
    ('tests = "here"\n', "no [tests] table"),
    ('[tests]\nplace = "here"\ncommands = ["a"]\nselect = ["b"]\n', "'select'"),
    ('[tests]\nplace = "github"\ncommands = ["a"]\n', "place = 'github'"),
    ('[tests]\ncommands = ["a"]\n', "place = None"),
    ('[tests]\nplace = "here"\n', "commands must be"),
    ('[tests]\nplace = "here"\ncommands = []\n', "commands must be"),
    ('[tests]\nplace = "here"\ncommands = "a"\n', "commands must be"),
    ('[tests]\nplace = "here"\ncommands = ["a", " "]\n', "commands must be"),
    ('[tests]\nplace = "here"\ncommands = ["a", 1]\n', "commands must be"),
    ('[tests\n', "is not TOML"),
])
def test_a_declaration_it_cannot_run_is_refused(text, said):
    with pytest.raises(Refused, match=re.escape(said)):
        status.declared_tests(text)
