"""The limits of one episode, in one place."""

# At most that many files go into one episode.
MAX_SOURCES = 10
# Longest material and longest script, in characters.
MAX_CHARS = 100_000
# A script never grows past this, one contribution never past that.
MAX_LINES = 250
MAX_LINE_CHARS = 1200
# Contributions one model call writes, so a call stays inside the provider's few minutes.
LINES_PER_CALL = 27
# The gaps between two contributions: after a quick reaction, normally, after a long explanation.
PAUSES = (0.12, 0.25, 0.45)
# Speech requests at the same time.
TTS_PARALLELISM = 4
# Longest instruction the caller may add.
INSTRUCTION_MAX_CHARS = 500
# Characters per speech request. Many servers give up on a request that asks for more
# than about a minute of audio, so a long contribution goes out in short parts.
CHUNK_CHARS = 400
# Seconds the voicing of one episode may take before it gives up. A hanging server
# must not cost a night, and the longest episode stays well inside it.
VOICING_SECONDS = 1800
# What the task and the answer schema of one call take up in the model window.
PROMPT_TOKENS = 3_000
OUTPUT_TOKENS = 4_000
# Characters one token carries, measured on prose with the usual tokenizers.
CHARS_PER_TOKEN = 3.0
# A model whose window nobody named is treated as having this one.
DEFAULT_WINDOW_TOKENS = 131_072
# Below this a window carries no useful share of the material and the run is refused.
MIN_WINDOW_TOKENS = 16_384
# Topics one part of the material is boiled down to when the whole does not fit,
# and how many topics an episode works from at most.
MAX_TOPICS_PER_PART = 25
MAX_TOPICS_TOTAL = 50
# A plan gives every file at least this share of the weight it has in the material,
# otherwise it is asked for once more. Files below a twentieth are spared.
FILE_WEIGHT_FLOOR = 0.25
MIN_FILE_SHARE = 0.05
