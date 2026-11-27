# jalon

jalon carries a piece of work from a scoped GitHub issue to a merged, deployed
change. GitHub is the record and the gate; jalon is thin commands over `gh`
and git, and one skill.

It needs Python 3.15, `gh`, git and gitleaks, and has no other dependency.

## What is here so far

| Piece | What it does |
|---|---|
| `skills/scope/` | The `scope` skill: narrows a conversation to one issue an agent can pick up, with nine sections, a checkable "Done when" and a review depth. |
| `jalon park file` | Files one issue, after checking the nine sections. The check catches a forgotten section or "Done when" line; it is not a guard against hidden or oddly formatted text, and a person reads every issue before it is filed. Without `--repo` it files into the checkout's repository, host included, read with `GH_REPO` left out. |
| `jalon park close` | Records a decision GitHub shows closed as completed: its record in `decisions/` at the top of the checkout, with one line in `decisions/index.jsonl`. It refuses an open issue and changes nothing on GitHub. A decision it replaces loses its record through `git rm` on `decisions/<number>-*.md`: git refuses a record that is modified, staged or not tracked, and the removal is left staged. A close that finds a record (or its `.part` file) or a line already there for the decision refuses and names it; a person reconciles it with git. With `--repo`, the repository the issue was closed in, it refuses one that is not the checkout's. |
| `jalon leak text\|dir\|commits` | Refuses a text, a folder or a range of commits that holds a secret or a name on the machine's private list: file contents, file names and link targets, commit messages, authors and committers, and what a merge's resolution adds. |
| `jalon push` | `git push` with that check forced on, on what the destination does not hold, ref names and tags included; an option that skips hooks is refused, and the repository's own pre-push hook still runs. |

## The private list

Nothing private may reach a public repository: not in a file, a commit
message, an author line, or an issue jalon files. The check is gitleaks with
one rule file kept outside every repository, `~/.config/jalon/private.toml`
(or the file `JALON_PRIVATE_LIST` names): gitleaks' default rules plus the
owner's own names. Only that file can set a finding aside: `gitleaks:allow`
comments are ignored, and a `.gitleaksignore` in what is scanned refuses. A
machine without that file cannot send anything to a public repository
through jalon. A repository GitHub does not report as `PRIVATE` is public.

The check does not catch:

- a private fact told in other words, or a name that is not on the list;
- anything in an image;
- a file that a rule on paths alone would match, when it is empty or renamed
  without change: such a rule is applied to files with content;
- a later push from a repository whose Git LFS content is already public: a
  push that introduces or changes an LFS pointer is refused, and the next one
  that changes none is not;
- an issue's assignee, which `park file` sends unchecked: a GitHub login is
  public by nature;
- git push options (`git push -o`), which `jalon push` passes to the
  destination unchecked;
- a `jalon` command that is not jalon: it is an ordinary Python program, so a
  `PYTHONPATH` that names a folder holding another `jalon` module, or a
  module named as one jalon imports, replaces that code before any check
  runs. The hook `jalon push` hands to git is isolated from that: it runs the
  jalon that wrote it, whatever the repository being pushed or the
  environment holds.

`park close` leaves two things to git and to the person who runs it. A record
marked `git update-index --assume-unchanged` is removed as git sees it, an
uncommitted edit included. And `decisions/` is a plain folder of the
checkout: if it is a link, a record is written where the link leads, and a
replacement is refused, since git finds no record of the checkout behind it.

A deposit in a project's inbox folder is deleted with `rm`, once it is filed
or set aside: jalon has no command for it.

## Before a repository's first `park file`

The issues it files carry labels the repository must hold: `decision`,
`parked`, and the three review depths. Create them once:

    gh label create decision --repo <owner/name>
    gh label create parked --repo <owner/name>
    gh label create none --repo <owner/name>
    gh label create quick --repo <owner/name>
    gh label create full --repo <owner/name>

The `scope` skill is copied from this repository's `skills/scope/` into the
skills folder of the agent that scopes (for Claude Code, `.claude/skills/scope/`
in the project): the built package carries the commands only, not the skill.

## Tests

    uv run --python 3.15 pytest

Tests call the code from inside. `tests/test_outside.py` is the exception: it
runs the real command in a scratch repository with a stand-in `gh`, once for
each command's main path and once for each refusal that guards a boundary.
`tests/test_alone.py` runs a copy of the folder's tests elsewhere and fails
if any of its Python processes opens a file under this repository or the
user's home.
