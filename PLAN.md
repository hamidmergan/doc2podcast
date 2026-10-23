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
  material and the plan decides the subject of the part.
- No job folder, no database, no queue. A run happens in one process and the result is
  returned as bytes or written to a file.
- The spoken note at the start is an option (`--intro-note`) and carries the text the
  caller gives. It is also written into the MP3 metadata comment.
- A single voice provider for all speakers. Each person picks a voice of that provider,
  so the voice fallback across providers has no place here.

## Steps

- [x] 0 Scaffold: repo, LICENSE, pyproject, package layout, CI, PLAN, README skeleton
- [x] 1 Core: script generation, Markdown script format, voicing, joining, config, errors
- [x] 2 API and CLI
- [x] 3 Tests with a fake chat and speech server
- [x] 4 README, CHANGELOG 0.1.0, local smoke test
- [x] 5 English sweep and acceptance
- [x] 6 Web UI and Docker

## Open

- `doc2speech` is not on a package index yet, so `pip install doc2podcast` and the CI
  job cannot resolve it. Until it is published, install it from its own checkout and
  drop its wheel into `wheels/` before building the image.
