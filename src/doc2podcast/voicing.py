"""Every contribution gets its voice, then one file to listen to."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from typing import Callable, List, Optional

from .audio import join
from .config import Settings
from .errors import AudioError, ConfigError, LimitError, ModelError, PodcastError
from .schemas import Line, Person, PodcastParams

logger = logging.getLogger(__name__)

# The provider stumbles now and then, these pauses are enough to get past it.
RETRY_PAUSES = (2.0, 5.0, 10.0)
# Four attempts for one contribution, and the speech library adds none of its own.
ATTEMPTS = len(RETRY_PAUSES) + 1

# Called with the finished and the total number of contributions.
Progress = Callable[[int, int], None]


class StageClock:
    """Counts the working time of the voicing, asked before each new contribution."""

    def __init__(self, seconds: float) -> None:
        self._start = time.monotonic()
        self._seconds = seconds

    def spent(self) -> float:
        return time.monotonic() - self._start

    def over(self) -> bool:
        return self.spent() >= self._seconds


def clock_for(settings: Settings) -> Optional[StageClock]:
    """The clock of one voicing, or none when the caller turned the budget off."""
    return StageClock(settings.stage_seconds) if settings.stage_seconds > 0 else None


def _speech_errors():
    """The errors of the speech library that no retry can change, empty without it."""
    try:
        from doc2speech import (
            AudioError as SpeechAudio,
            ConfigError as SpeechConfig,
            EmptyTextError as SpeechEmpty,
            LimitError as SpeechLimit,
            UnsupportedFileError as SpeechUnsupported,
        )
    except ImportError:  # pragma: no cover - the library is a dependency
        return ()
    return (SpeechAudio, SpeechConfig, SpeechEmpty, SpeechLimit, SpeechUnsupported)


def permanent(exc: Exception) -> bool:
    """Whether asking the provider again would only cost time.

    A failed speech request says itself whether a second try can still work: a
    timeout or a 5xx can, a wrong key or an unknown voice cannot.
    """
    if isinstance(exc, (AudioError, ConfigError, LimitError)):
        return True
    verdict = getattr(exc, "transient", None)
    if verdict is not None:
        return not bool(verdict)
    speech = _speech_errors()
    return bool(speech) and isinstance(exc, speech)


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
        # The ladder below is the only retry on the speech side, so the library adds none.
        max_retries=0,
        # One knob, one meaning: the contributions run side by side here, the parts of
        # a long contribution go out one after the other.
        concurrency=1,
        max_chars_per_chunk=settings.chunk_chars,
        max_chars=settings.max_chars,
    )


def _with_retry(client, settings: Settings, text: str, voice: str, language: str,
                speed: float, sleep=None, clock: Optional[StageClock] = None,
                stop: Optional[Event] = None) -> bytes:
    # Looked up here and not in the signature, so a caller can watch the waiting.
    sleep = sleep or time.sleep
    last: Optional[Exception] = None
    for pause in (0.0,) + RETRY_PAUSES:
        if pause:
            # Do not keep dripping against a dead provider once the run is over anyway.
            if stop is not None and stop.is_set():
                break
            if clock is not None and clock.over():
                break
            sleep(pause)
        try:
            return speak_line(client, settings, text, voice, language, speed)
        except Exception as exc:  # every provider fault is treated the same
            if permanent(exc):
                # A wrong key or an unknown voice stays so, asking again only costs time.
                raise ModelError(str(exc))
            last = exc
            logger.warning("Podcast: voicing failed, next attempt in %ss: %s", pause, exc)
    raise ModelError(str(last))


def voice_lines(client, settings: Settings, lines: List[Line], params: PodcastParams,
                progress: Optional[Progress] = None, sleep=None,
                clock: Optional[StageClock] = None) -> List[bytes]:
    """Every contribution as audio, in the order of the script.

    The first contribution that cannot be voiced ends the whole voicing: the others
    would meet the same provider and only make the error slower.
    """
    pieces: List[Optional[bytes]] = [None] * len(lines)
    done = [0]
    stop = Event()
    lock = Lock()

    def one(index: int) -> None:
        if stop.is_set():
            # Another contribution already failed, this one would only cost time.
            return
        line = lines[index]
        person = _person(params, line)
        if not person.voice_id:
            stop.set()
            raise ConfigError("Contribution %d has no voice." % (index + 1))
        if clock is not None and clock.over():
            stop.set()
            raise LimitError(
                "Voicing gave up after %.0f seconds with %d of %d contributions done. "
                "Raise --stage-seconds or check the speech server."
                % (clock.spent(), done[0], len(lines))
            )
        try:
            audio = _with_retry(client, settings, line.text, person.voice_id,
                                params.language, params.speed, sleep, clock, stop)
        except PodcastError as exc:
            stop.set()
            raise ModelError("Contribution %d could not be voiced: %s" % (index + 1, exc))
        if not audio:
            logger.warning("Podcast: contribution %d came back empty and is left out",
                           index + 1)
        pieces[index] = audio
        with lock:
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
    clock = clock_for(settings)
    pieces: List[bytes] = []
    if params.intro_note:
        voice = params.persons[0].voice_id if params.persons else ""
        pieces.append(_with_retry(client, settings, params.intro_note, voice,
                                  params.language, params.speed, clock=clock))
    pieces.extend(voice_lines(client, settings, lines, params, progress, clock=clock))
    return join(pieces, note=params.intro_note)
