# doc2podcast

Turns documents into a podcast conversation and voices it as one MP3.

The tool reads PDF, DOCX, PPTX, TXT and MD files, plans the episode, writes a
conversation script for one to four speakers with a chat model, and voices every
contribution with a text-to-speech model. The pieces are joined with ffmpeg into one
MP3. Two paths exist next to the full run: `--script-only` writes the script as
Markdown for review, `--from-script` voices a reviewed script.

## Shape

- pip package `doc2podcast`, Python package `doc2podcast`
- library as the core, thin CLI as a wrapper, web UI under `doc2podcast serve`
- `doc2speech` does the speaking of a single contribution
- any OpenAI-compatible server: `base_url`, `model`, optional `api_key`, with its own
  variables for the speech side and a fallback to the chat values

## Decisions

- Length is given in minutes. 145 spoken words a minute and 27 words per contribution
  give the number of contributions, so 5, 10 and 20 minutes come out as 27, 54 and 107
  contributions.
- The episode is planned first, then written part by part, at most 27 contributions per
  call. Each call sees the plan, the last four contributions and the opening words of
  all earlier ones, so a long episode stays one conversation.
- Planning works on the whole material instead of numbered passages. The passage map of
  a large dossier is not part of this tool, so each part is written from the whole
  material and the plan decides the subject of the part. What that costs and what was
  rebuilt without it is written out under "Deliberate deviations" below.
- No job folder, no database, no queue. A run happens in one process and the result is
  returned as bytes or written to a file.
- The spoken note at the start is an option (`--intro-note`) and carries the text the
  caller gives. It is also written into the MP3 metadata comment.
- A single voice provider for all speakers. Each person picks a voice of that provider,
  so the voice fallback across providers has no place here.
- Voicing stops at the first error that cannot get better. A wrong key or an unknown
  voice is reported at once, a timeout or a 5xx gets the ladder of four attempts with
  pauses of 2, 5 and 10 seconds. The speech library reports the verdict itself, so no
  message text is parsed. `--stage-seconds` bounds the whole voicing on top of that.
- One knob, one meaning. The parallel voicing lives here, so the speech library is
  always called with `concurrency=1` and with the chunk and character limits of this
  run. `DOC2SPEECH_*` variables of the speech tool change nothing in a run.
- The voices of the cast that really speaks are what gets checked. A script read back
  from Markdown carries its voices in the head, so the settings may name none.

## Deliberate deviations

### No passage map

A passage map numbers the whole material once and hands a planning model numbers
instead of text. Dropping it was the one declared deviation, but it was declared too
narrowly: the first note said only that the plan lost its `refs` and `start` fields.
Those two really are harmless, nothing in the written script reads them. Four more
things hung on the same structure, and three of them are back by another route.

| What the map carried | State | How |
| --- | --- | --- |
| `refs` and `start` in the plan | Given up | Nothing in the script reads them. The `[file, p. N]` markers the prompts talk about come from the material itself. |
| A writing budget measured against the model window | Rebuilt | `budget.py` measures the material against `--context-window` before every call. |
| Topic summaries when the material does not fit the window | Rebuilt | `budget.Budget.fit` boils the material down to topics, one call per piece, and plan and parts then read the same shortened text. |
| A second planning call for files the plan left out | Rebuilt | `generate.too_light` weighs every file by characters, not by passage numbers, and `plan_episode` asks once more with the names and the percentages. |
| The guarantee that a passage is told once | Given up | See below. |

The budget was the serious one. Without it every part call carried the full material,
up to `--max-chars`, and a model with an 8k or 16k window was silently cut off by its
server at the end of the material, which is exactly where the last documents stand.
Rebuilt, the same case now costs one topic call per piece and the last documents still
get their say. A window under 16384 tokens is refused outright instead of producing a
half episode.

The second planning call was undeclared and is also back, on a different measure: the
source compared the passages a file holds against the passages the plan names, this
tool compares the share of characters a file holds against the share of file mentions
the plan gives it. Same purpose, no numbering needed.

What stays given up is the told-once rule. The source handed each part its own
passages, took a shared passage away from the later part (`exklusiv`) and gave an
unclaimed stretch to the nearest part (`abdecken`), so every passage was told exactly
once by exactly one part. Here every part sees the whole material, so nothing stops
two parts from reaching for the same page. What holds repetition back is prompt text
only: the plan a part sees, the last four contributions in full and the opening words
of all earlier ones. The reason to accept this is that the alternative is the map,
which is a tool of its own and far larger than this one. The cost is in the README
under Limitations.

### Two numbers of the window budget differ

- The smallest window accepted is 16384 tokens, half the source value. The source ran
  against servers it had measured and could insist on 32768. This tool is pointed at
  whatever a user runs, and a 16k window still carries about 28000 characters per call,
  which is a usable episode. Below that the run is refused with the flag named.
- The source gave every file at least two topics, so a file at the back of a long
  dossier could not fall out of the topic stage. That floor needed the passage map to
  know which file a topic came from. Here the material is cut into pieces at blank line
  boundaries and every piece is mapped on its own, so every piece contributes at least
  one topic, but the share a single file gets is not guaranteed. The topic prompt asks
  for the file name in the title instead, which is what the plan is then measured
  against.

## Known properties

Behaviour that is faithful to the source and kept on purpose, written down so a reader
does not take it for an oversight.

- A surplus part in a planning answer is folded into the last one. With passages the
  source merged the passages too, with no passages there is nothing to merge, so the
  part's title is dropped and its files move to the part before it.
- A contribution the speech server answers with zero bytes is left out of the episode.
  The source did the same. It is logged with its number now, because this tool has no
  job record to compare the result against.
- `--speakers` only sets how many people are cast. Who speaks when is a prompt rule,
  the same as in the source, so a weak model can put the turns in a different order.
- The length in minutes is a target, not a promise. The number of contributions is
  exact, the words per contribution are up to the model.
- `tts_model` has no fallback to the chat model on purpose. `tts_base_url` and
  `tts_api_key` do fall back, a model does not, because a chat model would answer a
  podcast with text.
- One job in memory on the web page. A second request while one runs gets 409 and a
  restart loses the script, which follows the decision "no job folder, no database, no
  queue".

## Steps

- [x] 0 Scaffold: repo, LICENSE, pyproject, package layout, CI, PLAN, README skeleton
- [x] 1 Core: script generation, Markdown script format, voicing, joining, config, errors
- [x] 2 API and CLI
- [x] 3 Tests with a fake chat and speech server
- [x] 4 README, CHANGELOG 0.1.0, local smoke test
- [x] 5 English sweep and acceptance
- [x] 6 Web UI and Docker

## Open

- `doc2speech` is not on a package index yet, so neither `pip install doc2podcast` nor
  a plain `pip install .` in the clone can resolve it. Until it is published:
  - README Installation and Running Tests name it and give the install path
    (`pip install ./doc2speech` or `pip install -e ../doc2speech`) before this tool.
  - `pyproject.toml` keeps the normal dependency `doc2speech>=0.1` with a comment
    saying where it comes from, so publishing it needs no change here.
  - The CI job checks the doc2speech repository out next to this one and installs it
    from that source, so the workflow is green rather than left red.
  - The Dockerfile takes it from `wheels/` through `--find-links`. Drop a wheel in with
    `pip wheel --no-deps -w wheels ../doc2speech` before building the image.
    `wheels/*.whl` is git ignored, only `wheels/README.md` is tracked.
- The CI job installs ffmpeg. Without it every test that voices or joins audio skips
  and the run still reports green, which would say nothing about half of the tool.
