"""The shapes the podcast passes between planning, writing and voicing."""

from typing import List, Tuple

from pydantic import BaseModel, Field

ROLES: Tuple[str, ...] = ("host", "expert", "student", "critic")
STYLES: Tuple[str, ...] = ("teaching", "casual", "interview")
LANGUAGES: Tuple[str, ...] = ("de", "en")

# Speaking tempo and the range the voices are asked for.
SPEED_MIN, SPEED_MAX, SPEED_DEFAULT = 0.7, 1.2, 0.9

# A model keeps a count of paragraphs far better than a total word count, so the target
# is stated as (contributions, words each) and the sum only follows from it. One long turn in
# three among shorter replies averages about 27 words.
WORDS_PER_LINE = 27
# Spoken words a minute, the number that turns a wish in minutes into contributions.
WORDS_PER_MINUTE = 145

MINUTES_MIN, MINUTES_MAX, MINUTES_DEFAULT = 1.0, 60.0, 10.0

# What the page offers as a length, in minutes.
LENGTH_MINUTES = {"short": 5.0, "medium": 10.0, "long": 20.0}

# The names a cast gets when the caller only says how many people speak.
DEFAULT_NAMES = ("Ana", "Ben", "Cleo", "Dan")
# The role of the first, second, third and fourth person.
DEFAULT_ROLES = ("host", "expert", "student", "critic")


def length_plan(minutes: float) -> Tuple[int, int]:
    """How many contributions a wish in minutes asks for, and the words each one gets."""
    from .limits import MAX_LINES

    lines = int(round(minutes * WORDS_PER_MINUTE / WORDS_PER_LINE))
    return max(2, min(lines, MAX_LINES)), WORDS_PER_LINE


class Person(BaseModel):
    """One voice of the podcast."""

    name: str = Field(min_length=1, max_length=60)
    role: str = "host"
    voice_id: str = ""


class Line(BaseModel):
    """One contribution of one person, the unit that gets voiced."""

    id: str = ""
    speaker: int = 0
    text: str = ""


class PodcastParams(BaseModel):
    """Everything planning, writing and voicing need, decided once at the start."""

    language: str = "de"
    instructions: str = ""
    speed: float = SPEED_DEFAULT
    persons: List[Person]
    minutes: float = MINUTES_DEFAULT
    style: str = "teaching"
    # A spoken note that opens the episode, empty when there is none.
    intro_note: str = ""
    source_label: str = ""
    # The instruction named something the material does not cover, so it dropped out.
    instruction_unmatched: bool = False
    # What the instruction turned out to be, decided once per run, see instructions.py.
    instruction_way: str = ""
    # Which settings the head of a read script really named, empty for a fresh script.
    head_keys: List[str] = []
