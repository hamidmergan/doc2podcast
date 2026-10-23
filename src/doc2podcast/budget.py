"""How much material one call may carry, and what to do when it does not fit.

The whole material goes into the planning call and into every part call, so the
window of the chat model is the limit that decides. A dossier that is larger than
the window would be cut off by the server, and it would always be cut off at the
end, where the last documents stand. Instead the material is boiled down to the
topics it covers, one call per piece, and the episode is planned and written from
those topics, so every document still has its say.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from .errors import ConfigError, ModelError
from .limits import (
    CHARS_PER_TOKEN,
    MAX_TOPICS_PER_PART,
    MAX_TOPICS_TOTAL,
    MIN_WINDOW_TOKENS,
    OUTPUT_TOKENS,
    PROMPT_TOKENS,
)

logger = logging.getLogger(__name__)

# Topic calls that run at the same time, as many as the voicing allows itself.
TOPIC_PARALLELISM = 4

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def window_chars(window_tokens: int) -> int:
    """How much text one call may carry on a model with this window."""
    if window_tokens < MIN_WINDOW_TOKENS:
        raise ConfigError(
            "A context window of %d tokens is too small for an episode, at least %d "
            "are needed (--context-window or DOC2PODCAST_CONTEXT_WINDOW)."
            % (window_tokens, MIN_WINDOW_TOKENS)
        )
    return max(1, int((window_tokens - PROMPT_TOKENS - OUTPUT_TOKENS) * CHARS_PER_TOKEN))


def pieces(material: str, limit: int) -> List[str]:
    """The material cut into as few pieces as the window allows, at block boundaries."""
    blocks = [b for b in (material or "").split("\n\n") if b.strip()]
    out: List[str] = []
    current = ""
    for block in blocks:
        if current and len(current) + len(block) + 2 > limit:
            out.append(current)
            current = ""
        current = block if not current else current + "\n\n" + block
        while len(current) > limit:
            # A single block longer than the window is cut where it has to be.
            out.append(current[:limit])
            current = current[limit:]
    if current:
        out.append(current)
    return out or [material]


def topic_messages(piece: str, number: int, parts: int, language: str, purpose: str,
                   most: int) -> List[dict]:
    """One piece of the material boiled down to its topics, when the whole does not fit."""
    system = (
        "You map a text. List the topics this text covers, in the order they appear, at "
        "most %d, spread over the whole text to its last line. This is part %d of %d of "
        "the material, other parts are mapped separately. For every topic give a short "
        "title and one sentence saying what the text states about it that names the "
        "concrete duties, deadlines and figures it gives. Keep the file name and the page "
        "the topic comes from in the title when the text shows them. Write titles and "
        "sentences in %s. The material will be used for: %s.\n"
        'Answer with one JSON object only: {"topics": [{"title": "...", "gist": "..."}]}'
        % (most, number, parts, language, purpose)
    )
    return [{"role": "system", "content": system},
            {"role": "user", "content": "/no_think\n%s" % piece}]


def parse_topics(raw: Optional[str], most: int) -> List[Tuple[str, str]]:
    """The topics out of one answer, a lost answer costs its topics and not the run."""
    text = _THINK.sub("", (raw or "").strip()).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    entries = data.get("topics") if isinstance(data, dict) else None
    out: List[Tuple[str, str]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        title = " ".join(str(entry.get("title") or "").split())[:120]
        if not title:
            continue
        out.append((title, " ".join(str(entry.get("gist") or "").split())[:300]))
        if len(out) >= most:
            break
    return out


def topic_block(topics: List[Tuple[str, str]]) -> str:
    return "\n".join("%d. %s: %s" % (i + 1, title, gist)
                     for i, (title, gist) in enumerate(topics))


class Budget:
    """Keeps the material inside the window of the chat model, for every call.

    The topics are paid for once: the first call that does not fit builds them, the
    planning call and every part call then read the same shortened material.
    """

    def __init__(self, ask, language: str, purpose: str, window_tokens: int):
        self.limit = window_chars(window_tokens)
        self._ask = ask
        self._language = "German" if language == "de" else "English"
        self._purpose = purpose
        self._short: Optional[str] = None

    def fits(self, material: str) -> bool:
        return len(material) <= self.limit

    def fit(self, material: str) -> str:
        """The material as this call may carry it, its topics when it is too long."""
        if self.fits(material):
            return material
        if self._short is None:
            self._short = self._summarise(material)
        return self._short

    def _summarise(self, material: str) -> str:
        parts = pieces(material, self.limit)
        most = max(1, min(MAX_TOPICS_PER_PART, MAX_TOPICS_TOTAL // len(parts)))
        calls = [topic_messages(piece, i + 1, len(parts), self._language, self._purpose, most)
                 for i, piece in enumerate(parts)]
        topics: List[Tuple[str, str]] = []
        for answer in self._answers(calls):
            topics.extend(parse_topics(answer, most))
        if not topics:
            raise ModelError(
                "The material is longer than the model window and no topics could be "
                "read from it. Give a model with a larger context window, or cut the "
                "material with --max-chars."
            )
        logger.info("Podcast: material of %d characters is talked about through %d topics",
                    len(material), len(topics))
        return topic_block(topics)[:self.limit]

    def _answers(self, calls: List[List[dict]]) -> List[Optional[str]]:
        def one(messages):
            try:
                return self._ask(messages)
            except Exception as exc:  # a lost piece costs its topics, not the run
                logger.warning("Podcast: topics of one piece not read (%s)", exc)
                return None

        if len(calls) == 1:
            return [one(calls[0])]
        with ThreadPoolExecutor(max_workers=min(TOPIC_PARALLELISM, len(calls))) as pool:
            return list(pool.map(one, calls))
