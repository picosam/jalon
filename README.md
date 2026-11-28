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
| `jalon status tests\|title` | Posts `jalon/tests` or `jalon/title` on a pull request's head commit: the tests the default branch declares in `jalon.toml`, run in this checkout, or the title against the private list. |

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
A push's destination is asked of GitHub only when it is written as an
address, `<scheme>://…` or `user@host:path`. Any other is scanned without
asking: `gh` would read a folder named `team/records` as a repository of
that name.
A list that extends another file names it by its full path: jalon runs
gitleaks from a folder of its own, where a relative path is not found, and a
folder or a push is then refused, clean or not.

### Where jalon's part ends

jalon decides three things about a scan: which bytes gitleaks is handed,
decoded how, and under what name.

- **Which bytes.** In a folder: every file, every name and link target. In a
  push: every file it sends, every path of each commit, each commit's and
  tag's own text, and each ref's name.
- **Decoded how.** Bytes that decode as UTF-8, or as UTF-16 when they open
  with its byte-order mark, are handed on decoded, after one line break.
  Bytes that do not decode are handed on as they are. A file is named in the
  output when its bytes do not decode, or hold a NUL: it may not be text.
  All of this goes by the bytes alone: an archive that happens to decode is
  handed on as a text is, and a UTF-32 text that opens with UTF-16's mark is
  decoded as UTF-16.
- **Under what name.** Each file goes to gitleaks under a number.

What gitleaks then reads of those bytes, and what it matches in them, is
gitleaks'. jalon makes no claim about it. Known with gitleaks 8.30.1:

- it reads a long text in blocks and matches inside each one: a name that
  lies across the end of a block is not matched. A text of some tens of
  thousands of bytes can be long enough;
- it skips, without a word, what it takes for a binary file by a signature.
  The line break jalon puts first is there for that: a text that opens with
  `%PDF`, `{\rtf` or `MZ` is read. A signature that sits further in still
  makes it skip the text: a tar archive's, 256 bytes into one;
- it matches every path in the list against the number a file is handed over
  under, never against the file's own path (see below);
- a rule's `keywords` can make it pass a spelling the rule's own pattern
  matches: seen with a Greek name written in the other letter case.

The line break has two costs. For bytes jalon decoded, a line number in a
refusal is one higher than in the file; for bytes handed on as they are it
is the file's own. And a rule anchored at the very start of a text no longer
matches there.

The check does not catch:

- a private fact told in other words, or a name that is not on the list;
- a file that is not text: an image, an archive, an office file, or a text
  in an encoding other than UTF-8, or UTF-16 with its byte-order mark. One
  whose bytes do not decode, or hold a NUL, is named in the output,
  `jalon: not read, as it is not text: '<name>'`; one whose bytes happen to
  decode without a NUL is not.
  The notice changes nothing by itself: such a file still goes to gitleaks,
  handed on as said above, the result is what gitleaks makes of it, and
  jalon does not check that. Archives are not opened: no member is taken
  out of one. In a push, a file that sits at several paths is named by one
  of them;
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
- content stored with Git LFS: it goes to another server, past this check,
  and jalon does not look for its pointers. A pointer is one more text;
- in a folder, a name or a link target that is not UTF-8: it reaches gitleaks
  with `?` in place of each such byte. In a push, a path that is not UTF-8
  is refused;
- content the destination already holds, which a push does not send: the
  same file under a new name is not read again, though its new name is.
  What it holds is asked of git by the push's address. Where git would read
  that address as another one, a remote of that name or a rewrite rule,
  nothing counts as held and the whole push is scanned. A remote of the
  address's very name, set to list through a program of its own, is not
  seen: what that program lists counts as held;
- a push that SSH or git sends somewhere else than its address reads: by a
  port, a host alias or a rewrite rule. GitHub's answer is about the owner
  and name in the address as `gh` reads it, which is not always the host git
  connects to (`gh` drops a leading `www.`), and a private one leaves that
  push unscanned;
- an issue's assignee, which `park file` sends unchecked: a GitHub login is
  public by nature;
- what a `pre-push` hook registered in git's configuration does
  (`hook.<name>.event`): git runs it before the check, and `jalon push`
  orders the repository's hook file only;
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
takes longer: about 10 seconds for 1,000 commits of 2,000 files. And
`jalon push` refuses a source written across lines, which git accepts: push
the commit's id.

`park close --replaces` checks nothing about the record it removes: it runs
`git rm` on `decisions/<number>-*.md` at the top of the checkout and shows
git's output. What git removes or refuses is git's to decide, in every state
of the checkout, and jalon looks at none of them: a file of that name that
is not the record, an edit that is staged, a file already gone from the
folder, a flag set on the index, a `decisions/` that is a link. Nor does
`park close`, with `--replaces` or without, look at where it writes: its
record and its index line go through a `decisions/` that is a link, wherever
it leads.

A deposit in a project's inbox folder is deleted with `rm`, once it is filed
or set aside: jalon has no command for it.

## What the merge gate enforces

The merge gate is three required statuses, `jalon/tests`, `jalon/title` and
`jalon/review`: GitHub requires them on a pull request's head commit, a new
head carries none until they are posted on it, and where the branch rule
accepts them from any app, as this repository's does, GitHub does not check
who posted them.

## Posting the tests and the title

`jalon status tests <n>` and `jalon status title <n>` post two of the three
statuses on pull request `<n>`'s head commit; `jalon/review` is posted by
hand.

`jalon status tests` reads `jalon.toml` as the repository's default branch
holds it on GitHub, so a pull request cannot change the commands that judge
it: the pull request that changes `jalon.toml` is judged by the commands the
default branch held before it. It runs each command of the `commands` list
under `[tests]`, in order, with `sh -c` at the top of the checkout, and posts
`success` when every one exits 0, or `failure` at the first that does not,
with that command's place in the list and its exit code. It refuses, and
posts nothing, unless the pull request is open, the checkout is at its head
commit, `git status --porcelain` prints nothing, and `[tests]` holds
`place = "here"` and a list of commands and nothing else. The commands run
with the rights of whoever runs it.

`jalon status title` passes the pull request's title through the private list
and posts `success` or `failure`. On a private repository it checks nothing
yet and posts nothing.

On a repository that is not private, each status's description passes the
private list before it is sent.

A status belongs to a commit, not to a title. Measured on 2026-11-28 with
`gh` 2.106.0: on a pull request whose head carried `jalon/title`, the title
was edited, and the commit's statuses and the pull request's checks still
showed `jalon/title` as `success`. A title edited after the post is not
checked until `jalon status title` runs again.

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
