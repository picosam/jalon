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
| `jalon park close` | Records a decision GitHub shows closed as completed: its record in `decisions/` at the top of the checkout, with one line in `decisions/index.jsonl`. It refuses an open issue and changes nothing on GitHub. A decision it replaces loses its record through `git rm` on `decisions/<number>-*.md`, whose own lines say what was removed; a removal is left staged, and if git refuses, jalon stops and writes no record. A close that finds a record (or its `.part` file) or a line already there for the decision refuses and names it; a person reconciles it with git. With `--repo`, the repository the issue was closed in, it refuses one that is not the checkout's. |
| `jalon leak text\|dir\|commits` | Refuses a text, a folder or a range of commits that holds a secret or a name on the machine's private list. In a folder: every text file's content, every file name and link target. In commits: the objects a push of them would send, each read whole as git stores it, with no patch in between: each new file, every path of each commit, and each commit's or tag's own text. A file that is not text is named in the output as not read. |
| `jalon push` | `git push` with that check forced on, on what the destination does not hold, ref names and tags included; an option that skips hooks is refused, and the repository's own pre-push hook still runs. |

## The private list

Nothing private may reach a public repository: not in a file, a commit
message, an author line, or an issue jalon files. The check is gitleaks with
one rule file kept outside every repository, `~/.config/jalon/private.toml`
(or the file `JALON_PRIVATE_LIST` names): gitleaks' default rules plus the
owner's own names. Only that file can set a finding aside: a `gitleaks:allow`
comment is ignored, and so is a `.gitleaksignore`, in the working folder or
in what is scanned. A
machine without that file cannot send anything to a public repository
through jalon. A repository GitHub does not report as `PRIVATE` is public.

### Where jalon's part ends

jalon decides three things about a scan: which bytes gitleaks is handed,
decoded how, and under what name.

- **Which bytes.** In a folder: every file, every name and link target. In a
  push: every file it sends, every path of each commit, each commit's and
  tag's own text, and each ref's name.
- **Decoded how.** Text is decoded once, as UTF-8, or as UTF-16 by its
  byte-order mark, and handed on after one line break. Anything else is
  handed on unopened, and named in the output; so is a text that holds a
  NUL, though it is handed on decoded.
- **Under what name.** Each file goes to gitleaks under a number.

What gitleaks then reads of those bytes, and what it matches in them, is
gitleaks'. jalon makes no claim about it and does not work around it. Known
with gitleaks 8.30.1:

- it reads a text in blocks. One longer than 125,000 bytes, with no empty
  line between its bytes 100,000 and 125,000, is cut there, and a name that
  lies across the cut is not matched. On standard input the cut falls
  elsewhere, and not at the same place twice;
- it skips, without a word, what it takes for a binary file by a signature.
  The line break jalon puts first is there for that: a text that opens with
  `%PDF`, `{\rtf` or `MZ` is read. A signature that sits further in still
  makes it skip the text: a tar archive's, 256 bytes into one;
- it matches every path in the list against the number a file is handed over
  under, never against the file's own path (see below).

The line break has two costs. A line number in a refusal counts it, so it is
one higher than in the file. And a rule anchored at the very start of a text
matches nothing.

The check does not catch:

- a private fact told in other words, or a name that is not on the list;
- a file that is not text: an image, an archive, an office file, or a text
  in an encoding other than UTF-8, or UTF-16 with its byte-order mark. Each
  is named in the output, `jalon: not read, as it is not text: '<name>'`.
  The notice changes nothing by itself: the bytes of such a file are still
  handed to gitleaks, the result is what gitleaks makes of them, and jalon
  does not check that. Archives are not opened. In a push, a file that sits
  at several paths is named by one of them;
- what a rule finds by a file's path: gitleaks receives each text under a
  number, so that none of its own rules sets a file aside by its path, as
  they do a lock file, an `.svg` or `node_modules`. No rule with a path then
  works as written, whether the path stands alone or beside a pattern: not
  one of the list's, and not those of gitleaks' own that go by a file's name
  (with gitleaks 8.30.1, a password in a NuGet configuration and a PKCS12
  file pass). The same holds for a path in an allowance, and a path loose
  enough to match a number applies to the file handed over under it. A name
  is matched as text, in a file's path as in its content;
- a rule written for one shape of a commit's own text: a commit and a tag
  are read as git stores them, where the author's line opens with `author `;
  and a commit whose text is not UTF-8 is refused, clean or not;
- a later push from a repository whose Git LFS content is already public: a
  push that introduces or changes an LFS pointer is refused, and the next one
  that changes none is not;
- a Git LFS pointer in a form jalon does not know. It knows one by the line
  Git LFS writes at its top, today's and the one before its first release.
  Git LFS still reads other forms, an older address or a pointer after an
  empty line, and those pass;
- content the destination already holds, which a push does not send: the
  same file under a new name is not read again, though its new name is;
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

The commit scan can also refuse what a push does not send. It reads every
path of each commit it is given, those the destination already holds too: a
listed name in such a path refuses every push, until a commit renames it
away. It runs one `git ls-tree` per commit, so a first push of a long history
takes longer: about 10 seconds for 1,000 commits of 2,000 files.

`park close --replaces` checks nothing about the record it removes: it runs
`git rm` on `decisions/<number>-*.md` at the top of the checkout and shows
git's output. What git removes or refuses is git's to decide, in every state
of the checkout, and jalon looks at none of them: a file of that name that
is not the record, an edit that is staged, a file already gone from the
folder, a flag set on the index, a `decisions/` that is a link.

A deposit in a project's inbox folder is deleted with `rm`, once it is filed
or set aside: jalon has no command for it.

## Before a repository's first `park file`

The issues it files carry labels the repository must hold: `decision`,
`parked`, and the three review depths. Create them once, naming the
repository by its address, which keeps its host:

    repo=$(gh repo view --json url --jq .url)
    gh label create decision --repo "$repo"
    gh label create parked --repo "$repo"
    gh label create none --repo "$repo"
    gh label create quick --repo "$repo"
    gh label create full --repo "$repo"

The `scope` skill is copied from this repository's `skills/scope/` into the
skills folder of the agent that scopes (for Claude Code, `.claude/skills/scope/`
in the project): the built package carries the commands only, not the skill.

## Tests

    uv run --python 3.15 pytest

Tests call the code from inside. `tests/test_outside.py` is the exception: it
runs the real command in a scratch repository with a stand-in `gh`, once for
each command's main path and once for each refusal that guards a boundary.
`tests/test_alone.py` runs a copy of the folder's tests elsewhere and fails
if one of the Python processes it observes opens a file under this repository
or the user's home. It does not observe the hook `jalon push` hands to git,
which runs isolated from the environment the observation rides in.
