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
INSTRUCTION_MAX_CHARS = 2000
