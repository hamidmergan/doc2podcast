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
- An API key is optional. Many self-hosted servers do not need one.

If you run your own models, your documents stay on your own network. Nothing leaves
your machine or data center.

## Installation

```bash
pip install doc2podcast
```

Alternatively, you can install it from the source:

```bash
git clone https://github.com/hamidmergan/doc2podcast.git
cd doc2podcast
pip install .
```

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
| `timeout` / `--timeout` | `DOC2PODCAST_TIMEOUT` | 300 seconds |

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

## Limitations

Quality depends on the chosen models. A small chat model keeps the word count and the
turn taking less reliably, and a weak voice makes a long episode tiring. Check an
episode before you publish it.

A scanned PDF without a text layer carries no text, so it cannot become an episode.

The chat model writes from the material you give it. It may still get a detail wrong,
so check facts, figures and deadlines before you publish.

## Running Tests

```bash
pip install -e ".[test]"
pytest
```

The tests run against a local fake server and need no real model. Tests that join
audio are skipped when ffmpeg is missing.

## License

MIT
