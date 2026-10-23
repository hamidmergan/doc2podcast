"""Plan the material, then write the episode in parts."""

import logging
import math
from typing import Callable, List, Optional

from . import instructions, script
from .client import Ask
from .errors import ModelError, ScriptUnusable
from .limits import LINES_PER_CALL, MAX_LINES
from .schemas import Line, PodcastParams, length_plan

logger = logging.getLogger(__name__)

# One retry is enough: a second bad answer is a prompt problem, not chance.
ATTEMPTS = 2

PURPOSE = "a podcast episode for university teaching"
# The last contributions a part sees of what came before it.
SO_FAR_LINES = 4
# Of every earlier contribution a part sees only its opening words, enough to know the subject.
OPENING_WORDS = 12

# Called with the finished and the total number of parts.
Progress = Callable[[int, int], None]


def _with_attempts(ask: Ask, messages: List[dict], read, what: str):
    """One call, tried again once when the answer cannot be used."""
    last = ""
    for attempt in range(1, ATTEMPTS + 1):
        answer = ask(messages) or ""
        try:
            return read(answer)
        except ScriptUnusable as exc:
            last = str(exc)
            logger.warning("Podcast: %s attempt %d unusable: %s", what, attempt, exc)
    raise ModelError(last or "The model gave no usable result (%s)" % what)


def decide_instruction(ask: Ask, params: PodcastParams, material: str) -> None:
    """Decides once per run what the instruction is, every later step reads it here."""
    if params.instruction_way or not instructions.clean(params.instructions):
        return
    params.instruction_way = instructions.decide(ask, params.instructions, material, PURPOSE)
    # The caller shows the hint for a missing subject, nonsense drops out silently.
    params.instruction_unmatched = params.instruction_way == instructions.IGNORED
    logger.info("Podcast: the instruction counts as %s", params.instruction_way)


def plan_episode(ask: Ask, material: str, params: PodcastParams, parts: int,
                 files: Optional[List[str]] = None) -> List[dict]:
    """The episode in parts, each with its own subject."""
    return _with_attempts(
        ask,
        script.plan_messages(material, params, parts, files),
        lambda raw: script.parse_plan(raw, parts),
        "plan",
    )


def write_lines(ask: Ask, material: str, params: PodcastParams,
                files: Optional[List[str]] = None,
                progress: Optional[Progress] = None) -> List[Line]:
    """Plan the episode in parts, then write part after part from the whole material."""
    total, _per_line = length_plan(params.minutes)
    parts = max(1, int(math.ceil(total / float(LINES_PER_CALL))))
    decide_instruction(ask, params, material)
    plan = plan_episode(ask, material, params, parts, files)
    lengths = script.part_lengths(total, len(plan))
    overview = "\n".join("%d. %s: %s" % (i + 1, p["title"], p["gist"])
                         for i, p in enumerate(plan))
    if plan[-1].get("thread"):
        overview += "\n=> %s" % plan[-1]["thread"]
    lines: List[Line] = []
    for i, (part, count) in enumerate(zip(plan, lengths), start=1):
        if progress:
            progress(i - 1, len(plan))
        messages = script.build_messages(
            material, params, count=count, part=i, parts=len(plan), plan=overview,
            so_far=lines[-SO_FAR_LINES:], opening=plan[0].get("opening", ""),
            thread=plan[-1].get("thread", ""),
            covered=[" ".join(l.text.split()[:OPENING_WORDS])
                     for l in lines[:-SO_FAR_LINES]])
        fresh = _with_attempts(
            ask, messages,
            lambda raw: script.parse_answer(raw, len(params.persons)),
            "part %d" % i,
        )
        fresh = script.without_self_address(fresh, [p.name for p in params.persons])
        lines.extend(fresh)
    if progress:
        progress(len(plan), len(plan))
    return lines[:MAX_LINES]
