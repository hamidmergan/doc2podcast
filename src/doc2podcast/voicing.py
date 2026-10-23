"""Every contribution gets its voice, then one file to listen to."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional

from .audio import join
from .config import Settings
from .errors import ModelError
from .schemas import Line, Person, PodcastParams

logger = logging.getLogger(__name__)

# The provider stumbles now and then, these pauses are enough to get past it.
RETRY_PAUSES = (2.0, 5.0, 10.0)

# Called with the finished and the total number of contributions.
Progress = Callable[[int, int], None]


def _person(params: PodcastParams, line: Line) -> Person:
    if line.speaker < len(params.persons):
        return params.persons[line.speaker]
    return params.persons[0]


def speak_line(client, settings: Settings, text: str, voice: str, language: str,
               speed: float) -> bytes:
    """One contribution, voiced by the speech model."""
    from doc2speech import speak

    return speak(
        text,
        voice=voice,
        base_url=settings.tts_base_url,
        model=settings.tts_model,
        api_key=settings.tts_api_key,
        client=client,
        language=language,
        speed=speed,
        format="mp3",
        timeout=settings.timeout,
        max_retries=settings.max_retries,
    )


def _with_retry(client, settings: Settings, text: str, voice: str, language: str,
                speed: float, sleep=time.sleep) -> bytes:
    last: Optional[Exception] = None
    for pause in (0.0,) + RETRY_PAUSES:
        if pause:
            sleep(pause)
        try:
            return speak_line(client, settings, text, voice, language, speed)
        except Exception as exc:  # every provider fault is treated the same
            last = exc
            logger.warning("Podcast: voicing failed, next attempt in %ss: %s", pause, exc)
    raise ModelError(str(last))


def voice_lines(client, settings: Settings, lines: List[Line], params: PodcastParams,
                progress: Optional[Progress] = None, sleep=time.sleep) -> List[bytes]:
    """Every contribution as audio, in the order of the script."""
    pieces: List[Optional[bytes]] = [None] * len(lines)
    done = [0]

    def one(index: int) -> None:
        line = lines[index]
        person = _person(params, line)
        pieces[index] = _with_retry(client, settings, line.text, person.voice_id,
                                    params.language, params.speed, sleep)
        done[0] += 1
        if progress:
            progress(done[0], len(lines))

    if not lines:
        return []
    workers = max(1, min(settings.concurrency, len(lines)))
    if workers == 1:
        for index in range(len(lines)):
            one(index)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for result in [pool.submit(one, i) for i in range(len(lines))]:
                result.result()
    return [piece or b"" for piece in pieces]


def render_lines(client, settings: Settings, lines: List[Line], params: PodcastParams,
                 progress: Optional[Progress] = None):
    """The whole episode as MP3 bytes and its length in seconds.

    The spoken note opens the episode when there is one, and it also lands in the
    metadata comment of the file.
    """
    pieces: List[bytes] = []
    if params.intro_note:
        voice = params.persons[0].voice_id if params.persons else ""
        pieces.append(_with_retry(client, settings, params.intro_note, voice,
                                  params.language, params.speed))
    pieces.extend(voice_lines(client, settings, lines, params, progress))
    return join(pieces, note=params.intro_note)
