# The scope log: one JSON line per answer

Each run of the `scope` skill may be logged, so that the skill can be judged
on what it asked. One file per run, `spec-skill-log-<short name>.jsonl`, one
line per answer of the user.

Fields:

- `stage`: the run's short name; `turn`: 1-based, one per answer; `time`: UTC,
  of the user's message, read from the clock, or `null`.
- `asked`: the one question put, short.
- `gap`: the part of the issue the question was meant to settle: `scope`,
  `source-of-truth`, `mapping`, `naming`, `owner`, `done-criteria`,
  `evidence`, `removal`, `assumption` or `other`.
- `answer`: the user's words, verbatim.
- `outcome`: `decided`, `narrowed`, `deferred`, `reopened`,
  `challenged-and-held` or `challenged-and-changed`.
- `challenge`: the evidence raised against the answer, or `null`.
- `evidence`: the sources checked this turn (a URL or a command), or `[]`.
- `extra`: what the user volunteered beyond the question, or `null`.
- `open_after`: the issue's open points after this turn.

At close, one summary line:

    {"stage": …, "summary": true, "turns": N, "closed": "<UTC time>",
     "started_by": "typed /scope | phrase in the prompt | session prompt | none",
     "should_have_fired": [turns where the skill was wanted but did not load],
     "questions_that_narrowed": […], "questions_wasted": […],
     "brief_fields_that_emerged": […]}
