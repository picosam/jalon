# Working in this repository

This file is for whoever works here, a person or an agent. The README says
what jalon does and where it stops; this file says how a change here is
proved and judged, and how it is merged. Every rule in it is one the
maintainer has ruled. In the checkout, `jalon` is run as
`uv run --python 3.15 jalon`.

## What proves a change

Run each at the head commit; the pull request states what each printed.
The suite, in the checkout:

    uv run --python 3.15 pytest

The same suite in a clone made from a local path, in a folder that is in
no git checkout:

    d=$(mktemp -d) && git clone --quiet "$PWD" "$d/jalon" && (cd "$d/jalon" && uv run --python 3.15 pytest)

An export of the tracked files, through the leak check:

    e=$(mktemp -d) && git archive HEAD | tar -x -C "$e" && uv run --python 3.15 jalon leak dir "$e"

## The rules a review holds a change to

1. jalon's part of a scan ends where the README's section "Where jalon's part ends" says; what lies past it is not held against a change.
2. What another tool does with what it is handed, or sends elsewhere, is stated in the README as a limit, not guarded against in code.
3. Only a missed "Done when" line or a broken rule of this file blocks a change; anything else is a note, and a clean verdict may carry notes.
4. A test is shown failing without its fix for the answer to a review finding, once, and for nothing else.
5. New code is asked first: the issue says what new code the work needs and why nothing existing serves, or that it needs none.
6. Python 3.15 and the standard library only: no runtime dependency.
7. Every change goes through an issue and a pull request, small ones included.
8. A step is done by hand three times, on real work, before the command that does it is written.
9. A tag and a release are cut only on the maintainer's word.
10. Every push goes through `jalon push`.
11. Every title, body and comment sent to this repository passes `jalon leak text` first, as the very file that is sent.

## What a review does not report

- What a required status already shows.
- What the README states as a limit.

## How a change is merged here

The three statuses are posted by hand until the commands that post them exist.
The maintainer runs the merge, once the name GitHub would sign the squash commit with has passed `jalon leak text`.
