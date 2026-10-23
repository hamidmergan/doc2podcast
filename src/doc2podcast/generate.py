"""Plan the material, then write the episode in parts."""

import logging
import math
from typing import Callable, Dict, List, Optional, Tuple

from . import budget as budgets
from . import instructions, script
from .client import Ask
from .errors import ModelError, ScriptUnusable
from .limits import (
    DEFAULT_WINDOW_TOKENS,
    FILE_WEIGHT_FLOOR,
    LINES_PER_CALL,
    MAX_LINES,
    MIN_FILE_SHARE,
)
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


def too_light(plan: List[dict], shares: Optional[Dict[str, float]]) -> List[Tuple[str, int]]:
    """The files a plan hardly talks about, with the share of the material they hold.

    Naming a file in one part is not covering it: a part follows its title, and a file
    that only turns up in passing is talked over. A file gets at least a quarter of the
    weight it has in the material, files below a twentieth are spared.
    """
    named = [name for part in plan for name in dict.fromkeys(part.get("files") or [])]
    if not named or not shares:
        return []
    out: List[Tuple[str, int]] = []
    for name, share in shares.items():
        if share < MIN_FILE_SHARE:
            continue
        in_plan = sum(1 for n in named if n == name) / float(len(named))
        if in_plan < share * FILE_WEIGHT_FLOOR:
            out.append((name, int(round(share * 100))))
    return out


def plan_episode(ask: Ask, material: str, params: PodcastParams, parts: int,
                 files: Optional[List[str]] = None,
                 shares: Optional[Dict[str, float]] = None) -> List[dict]:
    """The episode in parts, each with its own subject.

    A plan that leaves a whole file out is asked for once more: a part follows its
    title, and a file no title names is talked over even when its text is right there.
    """
    # A plan on one subject leaves files out on purpose, asking again would drag them back in.
    focus = instructions.focus(params.instructions, params.instruction_way)
    weighed = bool(files) and len(files or []) > 1 and not focus
    best: Optional[List[dict]] = None
    missing: List[Tuple[str, int]] = []
    hint: List[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        plan = _with_attempts(
            ask,
            script.plan_messages(material, params, parts, files, hint),
            lambda raw: script.parse_plan(raw, parts, files),
            "plan",
        )
        gaps = too_light(plan, shares) if weighed else []
        if best is None or len(gaps) < len(missing):
            best, missing = plan, gaps
        if not missing:
            break
        hint = ["%s (%d %% of the material)" % (name, share) for name, share in missing]
        logger.warning("Podcast: plan attempt %d gives too little room to %s", attempt,
                       ", ".join("%s (%d %%)" % (n, s) for n, s in missing))
    return best or []


def write_lines(ask: Ask, material: str, params: PodcastParams,
                files: Optional[List[str]] = None,
                shares: Optional[Dict[str, float]] = None,
                progress: Optional[Progress] = None) -> List[Line]:
    """Plan the episode in parts, then write part after part from the whole material."""
    total, _per_line = length_plan(params.minutes)
    parts = max(1, int(math.ceil(total / float(LINES_PER_CALL))))
    budget = budgets.Budget(ask, params.language, PURPOSE, _window(ask))
    decide_instruction(ask, params, budget.fit(material))
    plan = plan_episode(ask, budget.fit(material), params, parts, files, shares)
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
            # Every part call carries the material again, so every one is measured.
            budget.fit(material), params, count=count, part=i, parts=len(plan),
            plan=overview,
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


def _window(ask: Ask) -> int:
    """The window the caller named, the usual one for a caller that named none."""
    settings = getattr(ask, "settings", None)
    return getattr(settings, "context_window", None) or DEFAULT_WINDOW_TOKENS
