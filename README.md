# doc2podcast

Turn documents into a podcast conversation and voice it as one MP3. A chat model plans
the episode and writes a script with one to four speakers, a text-to-speech model
voices every contribution, and ffmpeg joins the pieces into a single file.

doc2podcast currently reads:

- PDF
- DOCX, PPTX
- TXT, MD
- SRT, VTT (transcripts)

## Prerequisites

- Python 3.9 or newer
- A server with an OpenAI-compatible API and a **chat model** that writes the script
  (for example Ollama, vLLM, LM Studio, a university server or a cloud provider)
- A **text-to-speech model** on the same server or on one of its own
- `ffmpeg` on the PATH. It joins the voiced contributions into one MP3.
- `doc2speech`, the sibling tool that sends a single contribution to the speech model.
  It is not on PyPI yet, see Installation.
- An API key is optional. Many self-hosted servers do not need one.

If you run your own models, your documents stay on your own network. Nothing leaves
your machine or data center.

## Installation

The speaking is done by [doc2speech](https://github.com/hamidmergan/doc2speech), a
sibling tool from the same set of document tools. It is not on PyPI yet, so `pip` cannot
find it on any index and neither `pip install doc2podcast` nor a plain `pip install .`
in the clone can resolve it. Install doc2speech from its source first, then this tool:

```bash
git clone https://github.com/hamidmergan/doc2speech.git
pip install ./doc2speech

git clone https://github.com/hamidmergan/doc2podcast.git
pip install ./doc2podcast
```

The order matters. With doc2speech already installed, the dependency is satisfied and
the second command needs no index for it. If you keep the two checkouts side by side,
`pip install -e ../doc2speech` from the doc2podcast folder does the same job.

ffmpeg comes from your package manager, for example `brew install ffmpeg` or
`apt install ffmpeg`.

## Usage

### Command-Line

One document into one episode:

```bash
doc2podcast paper.pdf -o paper.mp3 --minutes 10 --voices alloy,echo \
  --base-url http://localhost:11434/v1 --model your-chat-model --tts-model your-speech-model
```

Write the script first, read it, change what you want:

```bash
doc2podcast paper.pdf --script-only -o paper.md \
  --base-url http://localhost:11434/v1 --model your-chat-model
```

Then voice the reviewed script. No chat model is needed for this step:

```bash
doc2podcast --from-script paper.md -o paper.mp3 --voices alloy,echo \
  --base-url http://localhost:11434/v1 --tts-model your-speech-model
```

Several documents become one episode. The plan decides what each part talks about:

```bash
doc2podcast rules.pdf slides.pptx notes.md -o episode.mp3 --minutes 20 \
  --speakers 3 --names Mia,Noah,Ida --roles host,expert,student --voices alloy,echo,nova
```

Without `-o` the output goes next to the first document (`paper.pdf` becomes
`paper.mp3`, or `paper.md` with `--script-only`). An existing file is never
overwritten, a number is added instead (`paper (1).mp3`). `-o -` writes to stdout.
Errors appear on stderr. The exit code is 2 for a missing or impossible setting and 1
for a failed run.

### Python API

```python
from doc2podcast import make_podcast

make_podcast(
    ["paper.pdf"],
    "paper.mp3",
    minutes=10,
    voices="alloy,echo",
    base_url="http://localhost:11434/v1",
    model="your-chat-model",
    tts_model="your-speech-model",
)
```

The two steps on their own:

```python
from doc2podcast import render, write_script

script = write_script(
    ["paper.pdf"],
    minutes=10,
    base_url="http://localhost:11434/v1",
    model="your-chat-model",
)
open("paper.md", "w").write(script)

# after reading and correcting the script
render(
    open("paper.md").read(),
    "paper.mp3",
    voices="alloy,echo",
    base_url="http://localhost:11434/v1",
    tts_model="your-speech-model",
)
```

Without an output path both `render` and `make_podcast` return the MP3 bytes.
`progress` is called with the finished and the total number of contributions.

### The script

`--script-only` writes Markdown. The head holds the cast and the settings, the
conversation follows as one line per contribution:

```markdown
# Podcast script

## Cast

- Ana (host, voice alloy)
- Ben (expert, voice echo)

## Settings

- Language: en
- Style: teaching
- Speed: 0.9

## Conversation

**Ana:** Hello and welcome to the episode.

**Ben:** Good to be here, let us start.
```

Change the text, add or remove contributions, rename the people, swap the voices.
`--from-script` reads the file back. A plain `Ana: ...` line works too, so a script
written by hand needs no head at all. Voices given on the command line beat the ones
in the file.

### Web UI

A small page in the browser, with the same fields and steps as the CLI:

```bash
pip install "doc2podcast[ui]"
doc2podcast serve
```

Then open http://127.0.0.1:8000. The page walks through five steps: Content, Cast,
Script, Voicing, Done. Drop your documents, pick the language and an optional
instruction, pick how many people speak and give each a name, a role and a voice,
let the script be written, read it and change it line by line, then have it voiced.
The finished episode plays on the page, the MP3, the script and the transcript can be
downloaded.

Base URL, models, key and voices come from the environment and can be changed in the
fields of the page. Empty fields keep the value the server was started with.

The page has no login. It listens on 127.0.0.1 by default, so only your own machine
can reach it. Use `--host 0.0.0.0` only in a network you trust, for example inside
Docker behind your own reverse proxy.

```bash
doc2podcast serve --host 0.0.0.0 --port 8000 --voices alloy,echo
```

### Docker

The image brings ffmpeg and starts the web page:

```bash
docker compose up
```

The page is then on http://127.0.0.1:8000. Settings come from `DOC2PODCAST_*`
environment variables, `docker-compose.yml` lists them all:

```bash
DOC2PODCAST_BASE_URL=http://host.docker.internal:11434/v1 \
DOC2PODCAST_MODEL=your-chat-model \
DOC2PODCAST_TTS_MODEL=your-speech-model \
DOC2PODCAST_VOICES=alloy,echo \
docker compose up
```

A server running on your own machine is reachable from inside the container as
`host.docker.internal`, not as `localhost`. If port 8000 is taken, set
`DOC2PODCAST_PORT`.

The CLI works in the image too:

```bash
docker compose run --rm doc2podcast doc2podcast --help
```

Wheels placed in `wheels/` are preferred over the package index while the image is
built. Today one wheel is needed, because doc2speech is not on the index yet. Build it
once from your checkout, then the image builds:

```bash
pip wheel --no-deps -w wheels ../doc2speech
docker compose build
```

### Settings

Order: argument, then environment variable, then default.

| Argument / flag | Environment variable | Default |
| --- | --- | --- |
| `base_url` / `--base-url` | `DOC2PODCAST_BASE_URL` | none, required |
| `model` / `--model` | `DOC2PODCAST_MODEL` | none, required for a script |
| `api_key` / `--api-key` | `DOC2PODCAST_API_KEY` (then `OPENAI_API_KEY`) | optional |
| `tts_base_url` / `--tts-base-url` | `DOC2PODCAST_TTS_BASE_URL` | the chat `base_url` |
| `tts_model` / `--tts-model` | `DOC2PODCAST_TTS_MODEL` | none, required for audio |
| `tts_api_key` / `--tts-api-key` | `DOC2PODCAST_TTS_API_KEY` | the chat `api_key` |
| `voices` / `--voices` | `DOC2PODCAST_VOICES` | none, one per speaker required for audio |
| `names` / `--names` | `DOC2PODCAST_NAMES` | Ana, Ben, Cleo, Dan |
| `roles` / `--roles` | `DOC2PODCAST_ROLES` | host, expert, student, critic |
| `speakers` / `--speakers` | `DOC2PODCAST_SPEAKERS` | as many as there are voices, else 2 |
| `minutes` / `--minutes` | `DOC2PODCAST_MINUTES` | 10 |
| `language` / `--language` | `DOC2PODCAST_LANGUAGE` | `en` (also `de`) |
| `style` / `--style` | `DOC2PODCAST_STYLE` | `teaching` (also `casual`, `interview`) |
| `speed` / `--speed` | `DOC2PODCAST_SPEED` | 0.9 (0.7 to 1.2) |
| `instructions` / `--instructions` | `DOC2PODCAST_INSTRUCTIONS` | none |
| `intro_note` / `--intro-note` | `DOC2PODCAST_INTRO_NOTE` | none |
| `max_chars` / `--max-chars` | `DOC2PODCAST_MAX_CHARS` | 100000 |
| `max_sources` / `--max-sources` | `DOC2PODCAST_MAX_SOURCES` | 10 |
| `concurrency` / `--concurrency` | `DOC2PODCAST_CONCURRENCY` | 4 |
| `chunk_chars` / `--chunk-chars` | `DOC2PODCAST_CHUNK_CHARS` | 400 characters |
| `context_window` / `--context-window` | `DOC2PODCAST_CONTEXT_WINDOW` | 131072 tokens |
| `timeout` / `--timeout` | `DOC2PODCAST_TIMEOUT` | 300 seconds |
| `max_retries` / `--max-retries` | `DOC2PODCAST_MAX_RETRIES` | 2 |
| `stage_seconds` / `--stage-seconds` | `DOC2PODCAST_STAGE_SECONDS` | 1800 seconds |
| `temperature` | `DOC2PODCAST_TEMPERATURE` | 0.4 |

Roles are `host`, `expert`, `student` and `critic`. They shape how a person talks, not
who speaks when. Every speaker needs a voice of their own, two people may not share one.

`--minutes` is turned into a number of contributions: 145 spoken words a minute and
27 words per contribution give 27 contributions for 5 minutes, 54 for 10 and 107 for
20. Episodes longer than 27 contributions are written in several calls, each one
seeing the plan and what was said before, so it stays one conversation.

`--instructions` takes a wish in any language. A wish that names a subject narrows the
whole episode to it. A wish that only says how the episode should be (shorter
sentences, for beginners) shapes the tone. A wish the material says nothing about
drops out instead of being invented.

`--intro-note` is spoken before the first contribution and also written into the
metadata comment of the MP3.

`--context-window` is the window of your chat model in tokens. The whole material goes
into the planning call and into every part call, so that window is the real limit. Name
the window your model has: material that does not fit is first boiled down to the
topics it covers, one extra call per piece, and the episode is planned and written from
those topics, so the last documents still get their say instead of being cut off by the
server. A window under 16384 tokens is refused.

`--concurrency` is the number of contributions voiced at the same time. The parts of a
single long contribution always go out one after the other, so the setting means one
thing and `DOC2SPEECH_*` variables of the speech tool change nothing here.

`--timeout` and `--max-retries` belong to the chat requests. Voicing has a ladder of
four attempts of its own, with pauses of 2, 5 and 10 seconds, and it stops at the first
error that cannot get better, a wrong key or an unknown voice for example.
`--stage-seconds` is the whole voicing: when the speech server hangs, the run gives up
after that many seconds instead of working through every contribution. `0` turns the
budget off.

## Limitations

Quality depends on the chosen models. A small chat model keeps the word count and the
turn taking less reliably, and a weak voice makes a long episode tiring. Check an
episode before you publish it.

A scanned PDF without a text layer carries no text, so it cannot become an episode.

The chat model writes from the material you give it. It may still get a detail wrong,
so check facts, figures and deadlines before you publish.

The whole material goes into the planning call and into every part call. A 20 minute
episode is four part calls, a 60 minute episode is ten, so the material crosses the
wire that many times. `--max-chars` caps what is sent at all, by default 100000
characters, and `--context-window` decides whether that still fits your model: what
does not fit is talked about through its topics instead of its full text, which costs
detail. A large dossier and a small window therefore give a flatter episode. Fewer or
shorter documents, or a model with a larger window, give a better one.

What each part talks about is decided by the plan and by the prompt, not by a division
of the material. Two parts can touch the same passage, so a long episode can repeat
itself. A plan that gives a file far too little room is asked for a second time, but a
subject mentioned twice is not caught.

## Running Tests

```bash
pip install -e ../doc2speech
pip install -e ".[test]"
pytest
```

The first line is the same story as in Installation: doc2speech is not on an index yet,
so point pip at your checkout of it. The path is wherever you cloned it.

The tests run against a local fake server and need no real model. Tests that join
audio are skipped when ffmpeg is missing, so install ffmpeg before you read a green
run as proof that the voicing works.

## License

MIT
