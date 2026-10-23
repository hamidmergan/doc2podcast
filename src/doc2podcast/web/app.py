"""Web API for the podcast page.

One job at a time: pick the material, pick the cast, let the script be written,
check it, have it voiced. Nothing is stored on disk, the script and the audio live
in memory until the next job replaces them.
"""

import threading
from pathlib import Path
from typing import List, Optional, Sequence
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import config, generate, markdown, sources
from ..client import Ask, make_client, make_speech_client
from ..config import Settings
from ..core import cast as default_cast
from ..core import params_from
from ..errors import ConfigError, PodcastError
from ..limits import MAX_LINE_CHARS, MAX_LINES, MAX_SOURCES
from ..schemas import LANGUAGES, LENGTH_MINUTES, ROLES, SPEED_DEFAULT, SPEED_MAX, SPEED_MIN, STYLES
from ..schemas import Line, Person
from ..voicing import render_lines

STATIC = Path(__file__).parent / "static"
MB = 1024 * 1024

# Largest upload the page accepts, over all files of one episode.
MAX_UPLOAD_MB = 50

# At most four people speak.
MAX_PERSONS = config.MAX_PERSONS


class LineIn(BaseModel):
    speaker: int = 0
    text: str = ""


class PersonIn(BaseModel):
    name: str = ""
    role: str = "host"
    voice: str = ""


class RenderRequest(BaseModel):
    lines: List[LineIn] = []
    persons: List[PersonIn] = []
    language: str = ""
    speed: Optional[float] = None
    intro_note: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    tts_base_url: str = ""
    tts_model: str = ""
    tts_api_key: str = ""


class Job:
    """The one job the page is working on, with its script and its audio."""

    def __init__(self) -> None:
        self.state = "idle"  # idle, running, done or error
        self.step = ""       # script, tts or joining
        self.done = 0
        self.total = 0
        self.error = ""
        self.name = "podcast"
        self.lines: List[Line] = []
        self.persons: List[Person] = []
        self.language = "en"
        self.minutes = 0.0
        self.instruction_unmatched = False
        self.audio = b""
        self.seconds = 0.0

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "step": self.step,
            "done": self.done,
            "total": self.total,
            "error": self.error,
            "name": self.name,
            "lines": [{"speaker": l.speaker, "text": l.text} for l in self.lines],
            "persons": [{"name": p.name, "role": p.role, "voice": p.voice_id}
                        for p in self.persons],
            "language": self.language,
            "minutes": round(self.seconds / 60.0, 1) if self.seconds else 0,
            "instruction_unmatched": self.instruction_unmatched,
            "has_audio": bool(self.audio),
        }


def _hostname(host: str) -> str:
    if host.startswith("["):
        return host[1:host.find("]")].lower()
    return host.rsplit(":", 1)[0].lower() if host.count(":") == 1 else host.lower()


def _stem(filename: str) -> str:
    """A safe file name stem for the download, from the uploaded name."""
    stem = Path(filename.replace("\\", "/")).stem
    cleaned = "".join(ch for ch in stem if ch.isalnum() or ch in " -_.").strip()
    return cleaned[:80] or "podcast"


def _split(value: str) -> List[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def create_app(settings: Optional[Settings] = None,
               allowed_hosts: Optional[Sequence[str]] = None,
               client=None, speech_client=None) -> FastAPI:
    """The podcast page and its JSON API.

    ``settings`` are the defaults of the page. Base URL, models, key and voices can
    also be typed into its fields. ``allowed_hosts`` limits the Host header (against
    DNS rebinding), requests from another origin are refused.
    """
    job = Job()
    lock = threading.Lock()

    app = FastAPI(title="doc2podcast")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    hosts = {h.lower() for h in allowed_hosts} if allowed_hosts is not None else None

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if hosts is not None and _hostname(host) not in hosts:
            return PlainTextResponse("Unknown host", status_code=400)
        origin = request.headers.get("origin")
        # also behind a reverse proxy
        own = {host.lower(), request.headers.get("x-forwarded-host", "").lower()}
        if origin is not None and urlsplit(origin).netloc.lower() not in own:
            return PlainTextResponse("Cross-origin requests are not allowed", status_code=403)
        if request.url.path == "/api/script":
            # refuse a too large upload before it is read, one MB for the form around it
            length = request.headers.get("content-length", "")
            if length.isdigit() and int(length) > MAX_UPLOAD_MB * MB + MB:
                return PlainTextResponse(
                    "The upload is larger than %d MB." % MAX_UPLOAD_MB, status_code=413)
        return await call_next(request)

    def fallback(name: str, given: str):
        value = (given or "").strip()
        if value:
            return value
        return getattr(settings, name, None) if settings else None

    def resolve(**given) -> Settings:
        try:
            return config.resolve(**given)
        except ConfigError as exc:
            raise HTTPException(400, str(exc))

    def start(step: str, total: int, name: str) -> None:
        with lock:
            if job.state == "running":
                raise HTTPException(409, "A podcast is already being made.")
            job.state, job.step, job.done, job.total = "running", step, 0, total
            job.error, job.name = "", name

    def failed(exc: Exception) -> None:
        # Every error ends the job. An error left running would block the page.
        with lock:
            job.state, job.error = "error", str(exc) or exc.__class__.__name__

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/info")
    def info():
        """What the page fills into its fields, and what it tells the user."""
        return {
            "base_url": settings.base_url if settings else "",
            "model": settings.model if settings else "",
            "tts_base_url": settings.tts_base_url if settings else "",
            "tts_model": settings.tts_model if settings else "",
            "voices": list(settings.voices) if settings else [],
            "names": list(settings.names) if settings else [],
            "roles": list(settings.roles) if settings else [],
            "speakers": settings.speakers if settings else 2,
            "language": settings.language if settings else "en",
            "style": settings.style if settings else "teaching",
            "speed": settings.speed if settings else SPEED_DEFAULT,
            "minutes": settings.minutes if settings else LENGTH_MINUTES["medium"],
            "has_key": bool(settings and settings.api_key != config.PLACEHOLDER_API_KEY),
            "languages": list(LANGUAGES),
            "styles": list(STYLES),
            "lengths": LENGTH_MINUTES,
            "role_names": list(ROLES),
            "max_persons": MAX_PERSONS,
            "max_sources": settings.max_sources if settings else MAX_SOURCES,
            "max_upload_mb": MAX_UPLOAD_MB,
            "max_lines": MAX_LINES,
            "speed_min": SPEED_MIN,
            "speed_max": SPEED_MAX,
            "extensions": list(sources.EXTENSIONS),
        }

    @app.post("/api/script")
    async def write(
        files: List[UploadFile] = File(default=[]),
        language: str = Form(""),
        style: str = Form(""),
        minutes: str = Form(""),
        speakers: str = Form(""),
        names: str = Form(""),
        roles: str = Form(""),
        voices: str = Form(""),
        speed: str = Form(""),
        instructions: str = Form(""),
        base_url: str = Form(""),
        model: str = Form(""),
        api_key: str = Form(""),
    ):
        chosen = resolve(
            base_url=fallback("base_url", base_url),
            model=fallback("model", model),
            api_key=fallback("api_key", api_key),
            language=fallback("language", language),
            style=fallback("style", style),
            minutes=_number(minutes, "Length"),
            speakers=_whole(speakers, "Number of people"),
            names=_split(names) or None,
            roles=_split(roles) or None,
            voices=_split(voices) or None,
            speed=_number(speed, "Speed"),
            instructions=instructions.strip() or None,
        )
        try:
            config.require_chat(chosen)
        except ConfigError as exc:
            raise HTTPException(400, str(exc))
        read = await _read_uploads(files, chosen)
        material = sources.material(read, chosen.max_chars)
        params = params_from(chosen, source_label=", ".join(s.name for s in read))
        name = _stem(read[0].name) if len(read) == 1 else "podcast"
        start("script", 0, name)

        def run():
            try:
                ask = Ask(client or make_client(chosen), chosen)
                lines = generate.write_lines(
                    ask, material, params, files=[s.name for s in read],
                    shares=sources.shares(read, chosen.max_chars),
                    progress=lambda done, total: _report(done, total))
            except Exception as exc:
                return failed(exc)
            with lock:
                job.state, job.step = "done", "script"
                job.lines, job.persons = lines, list(params.persons)
                job.language, job.minutes = params.language, params.minutes
                job.instruction_unmatched = params.instruction_unmatched
                job.audio, job.seconds = b"", 0.0

        threading.Thread(target=run, daemon=True).start()
        return {"state": "running"}

    def _report(done: int, total: int) -> None:
        with lock:
            job.done, job.total = done, total

    async def _read_uploads(files, chosen: Settings) -> List[sources.Source]:
        picked = [f for f in files if f and f.filename]
        if not picked:
            raise HTTPException(400, "Please add at least one file.")
        if len(picked) > chosen.max_sources:
            raise HTTPException(
                400, "That is too many files. At most %d go into one episode."
                     % chosen.max_sources)
        read = []
        size = 0
        for upload in picked:
            data = await upload.read()
            size += len(data)
            if size > MAX_UPLOAD_MB * MB:
                raise HTTPException(
                    413, "The files are larger than %d MB together." % MAX_UPLOAD_MB)
            try:
                read.append(sources.read_bytes(upload.filename or "", data))
            except PodcastError as exc:
                raise HTTPException(400, str(exc))
        return read

    @app.post("/api/render")
    def voice(request: RenderRequest):
        lines = [Line(speaker=max(0, l.speaker), text=l.text.strip()[:MAX_LINE_CHARS])
                 for l in request.lines if l.text.strip()][:MAX_LINES]
        if not lines:
            raise HTTPException(400, "There is no contribution to voice.")
        chosen = resolve(
            base_url=fallback("base_url", request.base_url),
            model=fallback("model", request.model),
            api_key=fallback("api_key", request.api_key),
            tts_base_url=fallback("tts_base_url", request.tts_base_url),
            tts_model=fallback("tts_model", request.tts_model),
            tts_api_key=fallback("tts_api_key", request.tts_api_key),
            language=fallback("language", request.language),
            speed=request.speed,
            intro_note=request.intro_note.strip() or None,
            voices=[p.voice for p in request.persons] or None,
            speakers=len(request.persons) or None,
        )
        persons = _persons(request, chosen)
        try:
            config.require_tts(chosen, len(persons), [p.voice_id for p in persons])
        except ConfigError as exc:
            raise HTTPException(400, str(exc))
        if max(l.speaker for l in lines) >= len(persons):
            raise HTTPException(400, "A contribution names a person who does not speak.")
        params = params_from(chosen, persons=persons)
        start("tts", len(lines), job.name)

        def run():
            try:
                speech = speech_client or make_speech_client(chosen)
                audio, seconds = render_lines(
                    speech, chosen, lines, params,
                    progress=lambda done, total: _report(done, total))
            except Exception as exc:
                return failed(exc)
            with lock:
                job.state, job.step = "done", "tts"
                job.lines, job.persons = lines, persons
                job.language = params.language
                job.audio, job.seconds = audio, seconds

        threading.Thread(target=run, daemon=True).start()
        return {"state": "running"}

    def _persons(request: RenderRequest, chosen: Settings) -> List[Person]:
        if not request.persons:
            return default_cast(chosen)
        out = []
        for index, person in enumerate(request.persons):
            name = person.name.strip() or "Person %d" % (index + 1)
            role = person.role if person.role in ROLES else "host"
            out.append(Person(name=name[:60], role=role, voice_id=person.voice.strip()))
        return out

    @app.get("/api/job")
    def state():
        with lock:
            return job.as_dict()

    @app.get("/api/audio")
    def audio():
        with lock:
            if not job.audio:
                raise HTTPException(404, "There is no audio yet.")
            data, name = job.audio, job.name
        return Response(
            content=data,
            media_type="audio/mpeg",
            headers={"Content-Disposition": 'attachment; filename="%s.mp3"' % name},
        )

    @app.get("/api/transcript")
    def transcript():
        with lock:
            if not job.lines:
                raise HTTPException(404, "There is no script yet.")
            text = markdown.transcript(job.lines, _params())
            name = job.name
        return Response(
            content=text,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="%s.txt"' % name},
        )

    @app.get("/api/script.md")
    def script_file():
        with lock:
            if not job.lines:
                raise HTTPException(404, "There is no script yet.")
            text = markdown.to_markdown(job.lines, _params())
            name = job.name
        return Response(
            content=text,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="%s.md"' % name},
        )

    def _params():
        """The settings of the script in memory, for the two downloads."""
        from ..schemas import PodcastParams

        return PodcastParams(persons=job.persons, language=job.language,
                             minutes=job.minutes or 10.0)

    return app


def _number(value: str, what: str) -> Optional[float]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise HTTPException(400, "%s must be a number." % what)


def _whole(value: str, what: str) -> Optional[int]:
    number = _number(value, what)
    return int(number) if number is not None else None
