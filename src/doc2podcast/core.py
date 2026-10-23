"""The three things the tool does: write a script, voice a script, do both at once."""

import logging
from pathlib import Path
from typing import List, Optional, Sequence, Union

from . import config, generate, markdown, sources
from .client import Ask, make_client, make_speech_client
from .config import Settings
from .errors import EmptyTextError, LimitError
from .render import render_lines
from .schemas import DEFAULT_NAMES, DEFAULT_ROLES, Line, Person, PodcastParams

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


def cast(settings: Settings, speakers: Optional[int] = None) -> List[Person]:
    """Who speaks, with the names, roles and voices the settings give or the defaults."""
    count = speakers or settings.speakers
    persons: List[Person] = []
    for index in range(count):
        name = settings.names[index] if index < len(settings.names) else _default_name(index)
        role = settings.roles[index] if index < len(settings.roles) else _default_role(index)
        voice = settings.voices[index] if index < len(settings.voices) else ""
        persons.append(Person(name=name, role=role, voice_id=voice))
    return persons


def _default_name(index: int) -> str:
    if index < len(DEFAULT_NAMES):
        return DEFAULT_NAMES[index]
    return "Speaker %d" % (index + 1)


def _default_role(index: int) -> str:
    return DEFAULT_ROLES[index] if index < len(DEFAULT_ROLES) else DEFAULT_ROLES[-1]


def params_from(settings: Settings, persons: Optional[List[Person]] = None,
                source_label: str = "") -> PodcastParams:
    """The settings of one run as the shape planning, writing and voicing read."""
    return PodcastParams(
        language=settings.language,
        instructions=settings.instructions,
        speed=settings.speed,
        persons=persons if persons is not None else cast(settings),
        minutes=settings.minutes,
        style=settings.style,
        intro_note=settings.intro_note,
        source_label=source_label,
    )


def read_sources(paths: Sequence[PathLike], settings: Settings) -> List[sources.Source]:
    """Every named file as a source, with the limits of one episode checked."""
    files = [Path(p) for p in paths]
    if not files:
        raise EmptyTextError("Name at least one file to make an episode from.")
    if len(files) > settings.max_sources:
        raise LimitError(
            "Too many files (%d). At most %d go into one episode."
            % (len(files), settings.max_sources)
        )
    read = sources.read_all(files)
    total = sum(len(s.text) for s in read)
    if total > settings.max_chars:
        logger.info("Material of %d characters is cut to %d.", total, settings.max_chars)
    return read


def write_script(
    paths: Sequence[PathLike],
    minutes: Optional[float] = None,
    speakers: Optional[int] = None,
    language: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    *,
    client=None,
    progress=None,
    **settings
) -> str:
    """Write the conversation script of an episode and return it as Markdown."""
    resolved = config.resolve(
        minutes=minutes, speakers=speakers, language=language,
        base_url=base_url, model=model, api_key=api_key, **settings
    )
    config.require_chat(resolved)
    read = read_sources(paths, resolved)
    material = sources.material(read, resolved.max_chars)
    params = params_from(resolved, source_label=", ".join(s.name for s in read))
    ask = Ask(client or make_client(resolved), resolved)
    lines = generate.write_lines(ask, material, params,
                                 files=[s.name for s in read], progress=progress)
    logger.info("Podcast: script with %d contributions", len(lines))
    return markdown.to_markdown(lines, params)


def render(
    script_md: str,
    output: Optional[PathLike] = None,
    voices=None,
    tts_base_url: Optional[str] = None,
    tts_model: Optional[str] = None,
    tts_api_key: Optional[str] = None,
    *,
    client=None,
    progress=None,
    **settings
):
    """Voice a reviewed script and return the MP3 bytes, or the path it was written to."""
    lines, from_script = markdown.from_markdown(script_md)
    # What the script was written with stands, the caller only adds the voices.
    for key, value in (("language", from_script.language), ("style", from_script.style),
                       ("speed", from_script.speed), ("intro_note", from_script.intro_note)):
        if settings.get(key) is None and value:
            settings[key] = value
    resolved = config.resolve(
        voices=voices, tts_base_url=tts_base_url, tts_model=tts_model,
        tts_api_key=tts_api_key,
        speakers=settings.pop("speakers", None) or len(from_script.persons),
        **settings
    )
    params = _voiced_params(resolved, from_script)
    config.require_tts(resolved, len(params.persons))
    speech = client or make_speech_client(resolved)
    audio, seconds = render_lines(speech, resolved, lines, params, progress)
    logger.info("Podcast: done, %.0fs from %d contributions", seconds, len(lines))
    if output is None:
        return audio
    target = Path(output)
    target.write_bytes(audio)
    return target


def _voiced_params(settings: Settings, from_script: PodcastParams) -> PodcastParams:
    """The cast that speaks: the script's people, with the voices the settings name."""
    persons: List[Person] = []
    for index, person in enumerate(from_script.persons):
        voice = settings.voices[index] if index < len(settings.voices) else person.voice_id
        persons.append(person.model_copy(update={"voice_id": voice}))
    return params_from(settings, persons=persons, source_label=from_script.source_label)


def make_podcast(
    paths: Sequence[PathLike],
    output: Optional[PathLike] = None,
    minutes: Optional[float] = None,
    speakers: Optional[int] = None,
    language: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    *,
    client=None,
    speech_client=None,
    progress=None,
    script_progress=None,
    **settings
):
    """Write the script and voice it in one run. Returns the MP3 bytes or the path."""
    resolved = config.resolve(
        minutes=minutes, speakers=speakers, language=language,
        base_url=base_url, model=model, api_key=api_key, **settings
    )
    config.require_chat(resolved)
    config.require_tts(resolved, resolved.speakers)
    read = read_sources(paths, resolved)
    material = sources.material(read, resolved.max_chars)
    params = params_from(resolved, source_label=", ".join(s.name for s in read))
    ask = Ask(client or make_client(resolved), resolved)
    lines = generate.write_lines(ask, material, params,
                                 files=[s.name for s in read], progress=script_progress)
    speech = speech_client or make_speech_client(resolved)
    audio, seconds = render_lines(speech, resolved, lines, params, progress)
    logger.info("Podcast: done, %.0fs from %d contributions", seconds, len(lines))
    if output is None:
        return audio
    target = Path(output)
    target.write_bytes(audio)
    return target


def script_lines(script_md: str) -> List[Line]:
    """The contributions of a written script, for a caller that wants to count them."""
    return markdown.from_markdown(script_md)[0]
