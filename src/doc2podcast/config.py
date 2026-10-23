"""Default values and resolution of settings.

Order: argument, then environment variable, then default. The speech side has its own
variables and falls back to the chat values where it has none of its own.
"""

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .errors import ConfigError
from .limits import MAX_CHARS, MAX_SOURCES, TTS_PARALLELISM
from .schemas import (
    LANGUAGES,
    MINUTES_DEFAULT,
    MINUTES_MAX,
    MINUTES_MIN,
    SPEED_DEFAULT,
    SPEED_MAX,
    SPEED_MIN,
    STYLES,
)

# Placeholder, because the OpenAI library requires a value. Local servers ignore it.
PLACEHOLDER_API_KEY = "none"

ENV_PREFIX = "DOC2PODCAST_"

# Seconds per request. Writing a part of the script takes a model a while.
TIMEOUT_SECONDS = 300
MAX_RETRIES = 2
# How creative the script may be. A plan and a script need room, but not too much.
TEMPERATURE = 0.4

# At most four people speak.
MAX_PERSONS = 4


@dataclass(frozen=True)
class Settings:
    """Everything one run needs, chat side and speech side."""

    base_url: Optional[str]
    model: Optional[str]
    api_key: str
    tts_base_url: Optional[str]
    tts_model: Optional[str]
    tts_api_key: str
    voices: Tuple[str, ...]
    names: Tuple[str, ...]
    roles: Tuple[str, ...]
    speakers: int
    minutes: float
    language: str
    style: str
    speed: float
    instructions: str
    intro_note: str
    max_chars: int
    max_sources: int
    concurrency: int
    timeout: float
    max_retries: int
    temperature: float


def _env(name: str) -> Optional[str]:
    value = os.environ.get(ENV_PREFIX + name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _pick(arg, env_name: str, default, cast):
    if arg is not None:
        return arg
    raw = _env(env_name)
    if raw is None:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ConfigError(
            f"Environment variable {ENV_PREFIX}{env_name} has an invalid value: {raw!r}"
        )


def _list(value) -> Tuple[str, ...]:
    """A comma separated list, from a string or from a list of strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)
    return tuple(str(item).strip() for item in items if str(item).strip())


def resolve(
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    tts_base_url: Optional[str] = None,
    tts_model: Optional[str] = None,
    tts_api_key: Optional[str] = None,
    voices=None,
    names=None,
    roles=None,
    speakers: Optional[int] = None,
    minutes: Optional[float] = None,
    language: Optional[str] = None,
    style: Optional[str] = None,
    speed: Optional[float] = None,
    instructions: Optional[str] = None,
    intro_note: Optional[str] = None,
    max_chars: Optional[int] = None,
    max_sources: Optional[int] = None,
    concurrency: Optional[int] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
    temperature: Optional[float] = None,
) -> Settings:
    """The settings of one run. Nothing is required here, the steps ask for what they need."""
    key = _pick(api_key, "API_KEY", None, str)
    if not key:
        key = os.environ.get("OPENAI_API_KEY") or PLACEHOLDER_API_KEY
    chat_base_url = _pick(base_url, "BASE_URL", None, str)
    chat_model = _pick(model, "MODEL", None, str)

    speech_key = _pick(tts_api_key, "TTS_API_KEY", None, str) or key
    voice_list = _list(voices) or _list(_env("VOICES"))
    name_list = _list(names) or _list(_env("NAMES"))
    role_list = _list(roles) or _list(_env("ROLES"))

    settings = Settings(
        base_url=chat_base_url,
        model=chat_model,
        api_key=key,
        # The speech side runs on the chat server unless it names its own.
        tts_base_url=_pick(tts_base_url, "TTS_BASE_URL", None, str) or chat_base_url,
        tts_model=_pick(tts_model, "TTS_MODEL", None, str),
        tts_api_key=speech_key,
        voices=voice_list,
        names=name_list,
        roles=role_list,
        speakers=_pick(speakers, "SPEAKERS", None, int) or (len(voice_list) or 2),
        minutes=float(_pick(minutes, "MINUTES", MINUTES_DEFAULT, float)),
        language=str(_pick(language, "LANGUAGE", "en", str)).lower(),
        style=str(_pick(style, "STYLE", "teaching", str)).lower(),
        speed=float(_pick(speed, "SPEED", SPEED_DEFAULT, float)),
        instructions=_pick(instructions, "INSTRUCTIONS", "", str),
        intro_note=_pick(intro_note, "INTRO_NOTE", "", str),
        max_chars=_pick(max_chars, "MAX_CHARS", MAX_CHARS, int),
        max_sources=_pick(max_sources, "MAX_SOURCES", MAX_SOURCES, int),
        concurrency=_pick(concurrency, "CONCURRENCY", TTS_PARALLELISM, int),
        timeout=_pick(timeout, "TIMEOUT", TIMEOUT_SECONDS, float),
        max_retries=_pick(max_retries, "MAX_RETRIES", MAX_RETRIES, int),
        temperature=_pick(temperature, "TEMPERATURE", TEMPERATURE, float),
    )
    _validate(settings)
    return settings


def _validate(s: Settings) -> None:
    if s.language not in LANGUAGES:
        raise ConfigError(
            f"language must be one of {', '.join(LANGUAGES)}, but is {s.language!r}."
        )
    if s.style not in STYLES:
        raise ConfigError(f"style must be one of {', '.join(STYLES)}, but is {s.style!r}.")
    if not 1 <= s.speakers <= MAX_PERSONS:
        raise ConfigError(f"speakers must be between 1 and {MAX_PERSONS}, but is {s.speakers}.")
    if not SPEED_MIN <= s.speed <= SPEED_MAX:
        raise ConfigError(f"speed must be between {SPEED_MIN} and {SPEED_MAX}, but is {s.speed}.")
    if not MINUTES_MIN <= s.minutes <= MINUTES_MAX:
        raise ConfigError(
            f"minutes must be between {MINUTES_MIN:g} and {MINUTES_MAX:g}, but is {s.minutes:g}."
        )
    positive = {
        "max_chars": s.max_chars,
        "max_sources": s.max_sources,
        "concurrency": s.concurrency,
        "timeout": s.timeout,
    }
    for name, value in positive.items():
        if value <= 0:
            raise ConfigError(f"{name} must be greater than 0, but is {value}.")
    if s.max_retries < 0:
        raise ConfigError("max_retries must not be negative.")


def require_chat(s: Settings) -> None:
    """The chat model writes the script, without it nothing can be written."""
    missing: List[str] = []
    if not s.base_url:
        missing.append("base_url (--base-url or DOC2PODCAST_BASE_URL)")
    if not s.model:
        missing.append("model (--model or DOC2PODCAST_MODEL)")
    if missing:
        raise ConfigError(
            "Missing: " + ", ".join(missing) + ". "
            "Example for a local server: base_url http://localhost:11434/v1 and a chat model."
        )


def require_tts(s: Settings, speakers: int, voices: Optional[Sequence[str]] = None) -> None:
    """The speech model voices the script, and every speaker needs a voice of their own.

    ``voices`` are the voices of the cast that really speaks. A script read back from
    Markdown carries the voices in its head, so the settings may well name none.
    """
    chosen = tuple(v for v in (s.voices if voices is None else voices) if v)
    missing: List[str] = []
    if not s.tts_base_url:
        missing.append("tts_base_url (--tts-base-url or DOC2PODCAST_TTS_BASE_URL)")
    if not s.tts_model:
        missing.append("tts_model (--tts-model or DOC2PODCAST_TTS_MODEL)")
    if len(chosen) < speakers:
        missing.append(
            f"{speakers} voices (--voices or DOC2PODCAST_VOICES), "
            f"{len(chosen)} given"
        )
    if missing:
        raise ConfigError(
            "Missing: " + ", ".join(missing) + ". "
            "Example for a local server: tts_base_url http://localhost:11434/v1, "
            "a text-to-speech model and one of its voices per speaker."
        )
    if len(set(chosen[:speakers])) < speakers:
        raise ConfigError("Every speaker needs a voice of their own, two share one here.")
