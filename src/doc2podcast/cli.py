import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import resolve
from .core import make_podcast, render, write_script
from .errors import ConfigError, PodcastError
from .schemas import LANGUAGES, ROLES, STYLES

LOOPBACK = ("127.0.0.1", "localhost", "::1")

UI_HINT = (
    "The web page needs the extra packages. Install them with "
    "'pip install \"doc2podcast[ui]\"'."
)

NO_LOGIN = (
    "Warning: the page has no login. On an address other than 127.0.0.1 "
    "everyone who can reach it can use your servers."
)

FORMATS = "Documents: .pdf, .docx, .pptx, .txt, .md, .srt or .vtt"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="doc2podcast",
        description="Turn documents into a podcast conversation and voice it as one MP3 "
                    "with any OpenAI-compatible chat and speech server.",
        epilog="Example: doc2podcast paper.pdf -o paper.mp3 --minutes 10 --voices alloy,echo. "
               "Run 'doc2podcast serve' for the web page.",
    )
    p.add_argument("files", nargs="*", help=FORMATS)
    p.add_argument("-o", "--output", help="Output file, '-' for stdout. "
                                          "Default: <first file>.mp3, or .md with --script-only")
    p.add_argument("--script-only", action="store_true",
                   help="Only write the script as Markdown, do not voice it")
    p.add_argument("--from-script", metavar="SCRIPT.md",
                   help="Voice a reviewed Markdown script instead of writing a new one")
    p.add_argument("--minutes", type=float, help="Wished length of the episode (default 10)")
    p.add_argument("--speakers", type=int, help="How many people talk, 1 to 4 (default 2)")
    p.add_argument("--names", help="Names of the speakers, comma separated, e.g. Ana,Ben")
    p.add_argument("--roles", help="Roles of the speakers, comma separated. One of: "
                                   + ", ".join(ROLES))
    p.add_argument("--voices", help="One voice of the speech model per speaker, "
                                    "comma separated, e.g. alloy,echo")
    p.add_argument("--language", choices=LANGUAGES, help="Language of the episode (default en)")
    p.add_argument("--style", choices=STYLES, help="Tone of the conversation (default teaching)")
    p.add_argument("--speed", type=float, help="Speaking speed, 0.7 to 1.2 (default 0.9)")
    p.add_argument("--instructions", help="What the episode should be about or how it should be")
    p.add_argument("--intro-note", help="A spoken note that opens the episode and goes "
                                        "into the metadata of the file")
    p.add_argument("--base-url", help="URL of the OpenAI-compatible chat server, "
                                      "e.g. http://localhost:11434/v1")
    p.add_argument("--model", help="Name of the chat model that writes the script")
    p.add_argument("--api-key", help="API key of the chat server, if it requires one")
    p.add_argument("--tts-base-url", help="URL of the speech server (default: the chat server)")
    p.add_argument("--tts-model", help="Name of the text-to-speech model")
    p.add_argument("--tts-api-key", help="API key of the speech server, if it requires one")
    p.add_argument("--max-chars", type=int,
                   help="Longest accepted material in characters (default 100000)")
    p.add_argument("--max-sources", type=int, help="Most files in one episode (default 10)")
    p.add_argument("--concurrency", type=int, help="Speech requests at the same time (default 4)")
    p.add_argument("--timeout", type=float, help="Seconds per request (default 300)")
    p.add_argument("--quiet", action="store_true", help="No progress on stderr")
    p.add_argument("--version", action="version", version="doc2podcast %s" % __version__)
    return p


def _serve_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="doc2podcast serve",
                                description="Start the local web page.")
    p.add_argument("--host", default="127.0.0.1", help="Default: 127.0.0.1 (this computer only)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--minutes", type=float, help="Length the page starts with")
    p.add_argument("--speakers", type=int, help="Number of speakers the page starts with")
    p.add_argument("--names", help="Names the page starts with, comma separated")
    p.add_argument("--roles", help="Roles the page starts with, comma separated")
    p.add_argument("--voices", help="Voices the page starts with, comma separated")
    p.add_argument("--language", choices=LANGUAGES, help="Language the page starts with")
    p.add_argument("--style", choices=STYLES, help="Style the page starts with")
    p.add_argument("--base-url", help="URL of the OpenAI-compatible chat server")
    p.add_argument("--model", help="Name of the chat model")
    p.add_argument("--api-key", help="API key of the chat server, if it requires one")
    p.add_argument("--tts-base-url", help="URL of the speech server")
    p.add_argument("--tts-model", help="Name of the text-to-speech model")
    p.add_argument("--tts-api-key", help="API key of the speech server, if it requires one")
    return p


def _serve(argv: List[str]) -> int:
    args = _serve_parser().parse_args(argv)
    try:
        import uvicorn

        from .web.app import create_app
    except ImportError:
        print(UI_HINT, file=sys.stderr)
        return 2
    # The page works without settings too, they can be typed into its fields.
    try:
        settings = resolve(
            base_url=args.base_url, model=args.model, api_key=args.api_key,
            tts_base_url=args.tts_base_url, tts_model=args.tts_model,
            tts_api_key=args.tts_api_key, voices=args.voices, names=args.names,
            roles=args.roles, speakers=args.speakers, minutes=args.minutes,
            language=args.language, style=args.style,
        )
    except ConfigError:
        settings = None
    app = create_app(
        settings,
        # on loopback, only accept our own host names, so other web pages cannot
        # reach it via DNS rebinding
        allowed_hosts=list(LOOPBACK) if args.host in LOOPBACK else None,
    )
    if args.host not in LOOPBACK:
        print(NO_LOGIN, file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _free(path: Path) -> Path:
    """Return path, or 'name (1).mp3', 'name (2).mp3', ... if it already exists."""
    candidate, n = path, 1
    while candidate.exists():
        candidate = path.with_name("%s (%d)%s" % (path.stem, n, path.suffix))
        n += 1
    return candidate


def _progress(what: str, quiet: bool):
    if quiet:
        return None

    def report(done: int, total: int) -> None:
        print("\r%s %d/%d" % (what, done, total), end="", file=sys.stderr)
        if done >= total:
            print(file=sys.stderr)

    return report


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        return _serve(argv[1:])
    args = _parser().parse_args(argv)

    if args.from_script and args.files:
        print("Please give either files or --from-script, not both.", file=sys.stderr)
        return 2
    if args.from_script and args.script_only:
        print("--from-script voices a script, so --script-only has nothing to do.",
              file=sys.stderr)
        return 2
    if not args.from_script and not args.files:
        print("Please name at least one document, or a script with --from-script.",
              file=sys.stderr)
        return 2

    options = dict(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        tts_base_url=args.tts_base_url,
        tts_model=args.tts_model,
        tts_api_key=args.tts_api_key,
        voices=args.voices,
        names=args.names,
        roles=args.roles,
        speakers=args.speakers,
        minutes=args.minutes,
        language=args.language,
        style=args.style,
        speed=args.speed,
        instructions=args.instructions,
        intro_note=args.intro_note,
        max_chars=args.max_chars,
        max_sources=args.max_sources,
        concurrency=args.concurrency,
        timeout=args.timeout,
    )
    to_stdout = args.output == "-"

    try:
        if args.from_script:
            script_md = Path(args.from_script).read_text(encoding="utf-8")
            audio = render(script_md, progress=_progress("Voicing", args.quiet),
                           **_speech_only(options))
            default = Path(args.from_script).with_suffix(".mp3")
        elif args.script_only:
            text = write_script(args.files, progress=_progress("Writing", args.quiet), **options)
            return _write_text(text, args, Path(args.files[0]).with_suffix(".md"), to_stdout)
        else:
            audio = make_podcast(
                args.files,
                script_progress=_progress("Writing", args.quiet),
                progress=_progress("Voicing", args.quiet),
                **options
            )
            default = Path(args.files[0]).with_suffix(".mp3")
    except ConfigError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 2
    except PodcastError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1

    if to_stdout:
        sys.stdout.buffer.write(audio)
        sys.stdout.buffer.flush()
        return 0
    # an explicitly named output file is overwritten, generated names never are
    target = Path(args.output) if args.output else _free(default)
    target.write_bytes(audio)
    print("Wrote %s" % target, file=sys.stderr)
    return 0


def _speech_only(options: dict) -> dict:
    """What voicing a finished script needs, the chat side has nothing left to do."""
    out = dict(options)
    for key in ("minutes", "names", "roles", "max_chars", "max_sources", "instructions"):
        out.pop(key, None)
    return out


def _write_text(text: str, args, default: Path, to_stdout: bool) -> int:
    if to_stdout:
        sys.stdout.write(text)
        sys.stdout.flush()
        return 0
    target = Path(args.output) if args.output else _free(default)
    target.write_text(text, encoding="utf-8")
    print("Wrote %s" % target, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
