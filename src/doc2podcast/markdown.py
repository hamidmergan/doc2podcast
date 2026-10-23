"""The script as Markdown, the form a person reads and corrects before it is voiced.

A script written out here can be read back in without losing anything the voicing
needs: who speaks, in which language, at which tempo and with which voice.
"""

import re
from typing import List, Optional, Tuple

from .errors import ScriptFormatError
from .limits import MAX_LINE_CHARS, MAX_LINES
from .schemas import Line, Person, PodcastParams

TITLE = "# Podcast script"

_HEAD_KEYS = ("language", "style", "speed", "intro note", "material")
# A contribution: "**Ana:** text", "**Ana**: text" or plain "Ana: text".
_LINE = re.compile(
    r"^\s*(?:\*\*|__)?\s*([^:*_]{1,60}?)\s*(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*(.+?)\s*$"
)
# A cast entry: "- Ana (host, voice alloy)".
_PERSON = re.compile(r"^\s*-\s*(.+?)\s*(?:\((.*)\))?\s*$")
_VOICE = re.compile(r"\bvoice\s+(\S+)")


def to_markdown(lines: List[Line], params: PodcastParams) -> str:
    """The script as one Markdown document, cast and settings in the head."""
    out: List[str] = [TITLE, ""]
    out.append("## Cast")
    out.append("")
    for person in params.persons:
        details = [person.role]
        if person.voice_id:
            details.append("voice %s" % person.voice_id)
        out.append("- %s (%s)" % (person.name, ", ".join(d for d in details if d)))
    out.append("")
    out.append("## Settings")
    out.append("")
    out.append("- Language: %s" % params.language)
    out.append("- Style: %s" % params.style)
    out.append("- Speed: %g" % params.speed)
    if params.intro_note:
        out.append("- Intro note: %s" % _one_line(params.intro_note))
    if params.source_label:
        out.append("- Material: %s" % _one_line(params.source_label))
    out.append("")
    out.append("## Conversation")
    out.append("")
    names = [p.name for p in params.persons]
    for line in lines:
        name = names[line.speaker] if line.speaker < len(names) else names[0] if names else "Speaker"
        out.append("**%s:** %s" % (name, _one_line(line.text)))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _one_line(text: str) -> str:
    return " ".join((text or "").split())


def from_markdown(text: str) -> Tuple[List[Line], PodcastParams]:
    """A reviewed script back into contributions and the settings that voice them.

    The cast comes from the head where it is written, and from the names in front of
    the contributions where it is not. A script no contribution can be read from is
    refused, so nobody voices an empty file.
    """
    head, body = _split(text or "")
    params = _params(head)
    names = [p.name for p in params.persons]
    lines: List[Line] = []
    for raw in body:
        found = _LINE.match(raw)
        if not found:
            _continue_last(lines, raw)
            continue
        name, said = found.group(1).strip(), found.group(2).strip()
        # A head without a "Conversation" heading is read here too, its keys are no cast.
        if not name or not said or _key(name) in _HEAD_KEYS:
            continue
        if name not in names:
            names.append(name)
            params.persons.append(Person(name=name, role=_role_for(len(names) - 1)))
        lines.append(Line(speaker=names.index(name), text=said[:MAX_LINE_CHARS]))
        if len(lines) >= MAX_LINES:
            break
    if not lines:
        raise ScriptFormatError(
            "No contribution found in the script. A line looks like '**Ana:** Hello.'"
        )
    return lines, params


def _key(name: str) -> str:
    """A head key as it is written in the head, with the list dash taken off."""
    return name.lstrip("-*\u2022").strip().lower()


def _continue_last(lines: List[Line], raw: str) -> None:
    """A contribution carried on over a second line belongs to the one before it."""
    text = raw.strip()
    if not lines or not text or text[0] in "#-*>|":
        return
    joined = ("%s %s" % (lines[-1].text, text))[:MAX_LINE_CHARS]
    lines[-1] = lines[-1].model_copy(update={"text": joined})


def _role_for(index: int) -> str:
    from .schemas import DEFAULT_ROLES

    return DEFAULT_ROLES[index] if index < len(DEFAULT_ROLES) else DEFAULT_ROLES[-1]


def _split(text: str) -> Tuple[List[str], List[str]]:
    """The head lines and the lines of the conversation, split at its heading."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for index, raw in enumerate(lines):
        if raw.strip().lower().lstrip("#").strip() == "conversation":
            return lines[:index], lines[index + 1:]
    return lines, lines


def _params(head: List[str]) -> PodcastParams:
    """Cast and settings out of the head, every one of them optional."""
    persons: List[Person] = []
    values = {}
    in_cast = False
    for raw in head:
        stripped = raw.strip()
        if stripped.startswith("#"):
            in_cast = stripped.lstrip("#").strip().lower() == "cast"
            continue
        key, _, value = stripped.lstrip("-").strip().partition(":")
        if key.strip().lower() in _HEAD_KEYS and value.strip():
            values[key.strip().lower()] = value.strip()
            continue
        if not in_cast:
            continue
        person = _PERSON.match(raw)
        if not person:
            continue
        name = person.group(1).strip()
        if not name:
            continue
        details = (person.group(2) or "").strip()
        persons.append(Person(name=name[:60], role=_role_from(details, len(persons)),
                              voice_id=_voice_from(details)))
    return PodcastParams(
        language=(values.get("language") or "en").lower()[:5],
        style=(values.get("style") or "teaching").lower(),
        speed=_speed(values.get("speed")),
        intro_note=values.get("intro note", ""),
        source_label=values.get("material", ""),
        persons=persons,
        # Only what the head really said, so an empty head leaves the environment alone.
        head_keys=[key.replace(" ", "_") for key in values],
    )


def _role_from(details: str, index: int) -> str:
    from .schemas import ROLES

    for part in details.split(","):
        word = part.strip().lower()
        if word in ROLES:
            return word
    return _role_for(index)


def _voice_from(details: str) -> str:
    found = _VOICE.search(details or "")
    if found:
        return found.group(1).strip().strip(",.")
    return ""


def _speed(value: Optional[str]) -> float:
    from .schemas import SPEED_DEFAULT

    try:
        return float(value)
    except (TypeError, ValueError):
        return SPEED_DEFAULT


def transcript(lines: List[Line], params: PodcastParams) -> str:
    """The plain reading text that goes next to the audio."""
    names = [p.name for p in params.persons]
    return "\n\n".join(
        "%s: %s" % (names[l.speaker] if l.speaker < len(names) else names[0], l.text)
        for l in lines
    ) + "\n"
