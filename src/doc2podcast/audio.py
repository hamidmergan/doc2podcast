"""Putting the voiced contributions together into one file to listen to."""

import logging
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import List, Optional, Tuple

from .errors import AudioError
from .limits import PAUSES
from .process import run_proc

logger = logging.getLogger(__name__)

# The voice leaves silence around every piece, only a short breath of it stays.
_EDGES = ("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.03,areverse,"
          "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.08,areverse")
_WAV = ["-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le"]
# A piece shorter than this is a quick reaction, one longer than the other an explanation.
_REACTION_S = 2.5
_EXPLANATION_S = 15.0
# Every voice arrives at its own loudness, each piece is brought to this mean level.
_TARGET_DB = -20.0
# Below this mean a piece is silence and keeps its level, the peak keeps this distance from clipping.
_SILENCE_DB = -60.0
_PEAK_DB = -1.0


def ffmpeg_path() -> str:
    """Where ffmpeg is, or a clear error naming what to install."""
    return _tool("ffmpeg", "It joins the voiced contributions into one file.")


def ffprobe_path() -> str:
    """Where ffprobe is, or a clear error naming what to install."""
    return _tool("ffprobe", "It measures how long a voiced piece is.")


def _tool(name: str, what: str) -> str:
    found = shutil.which(name)
    if not found:
        raise AudioError(
            "%s was not found. %s "
            "Install it, for example with 'brew install ffmpeg' or 'apt install ffmpeg'."
            % (name, what)
        )
    return found


def pause_before(before_s: float, after_s: float) -> float:
    """The gap between two pieces, a reaction comes quickly, a long explanation sinks in."""
    quick, normal, long_gap = PAUSES
    if after_s < _REACTION_S:
        return quick
    if before_s > _EXPLANATION_S:
        return long_gap
    return normal


def audio_duration(path: Path) -> float:
    """Audio length in seconds from the counted packets."""
    result = subprocess.run(
        [ffprobe_path(), "-v", "error", "-select_streams", "a:0",
         "-show_entries", "packet=duration_time", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise AudioError(f"ffprobe failed: {result.stderr[:200]}")
    total = 0.0
    for line in result.stdout.splitlines():
        try:
            total += float(line.strip().rstrip(","))
        except ValueError:
            continue
    if total <= 0:
        raise AudioError(f"audio length not measurable: {path}")
    return total


def _duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def _as_wav(raw: Path, target: Path) -> float:
    """One piece as WAV without its silent edges, a piece that is all silence stays whole."""
    result = None
    for filter_ in (["-af", _EDGES], []):
        result = run_proc(["ffmpeg", "-y", "-i", str(raw), *filter_, *_WAV, str(target)],
                          timeout=60)
        try:
            seconds = _duration(target) if result.returncode == 0 else 0.0
        except (wave.Error, OSError, EOFError):
            seconds = 0.0
        if seconds > 0.05:
            return seconds
    raise AudioError(f"contribution not readable: {(result.stderr if result else '')[-200:]}")


def _level(path: Path) -> Optional[Tuple[float, float]]:
    """Mean and peak level of a piece in dB, None when ffmpeg cannot tell."""
    result = run_proc(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                      timeout=60)
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", result.stderr or "")
    peak = re.search(r"max_volume: (-?[\d.]+) dB", result.stderr or "")
    if not mean or not peak:
        return None
    return float(mean.group(1)), float(peak.group(1))


def _level_out(path: Path) -> None:
    """Brings a piece to the common loudness, so no speaker sounds closer than the other."""
    level = _level(path)
    if level is None or level[0] < _SILENCE_DB:
        return
    mean, peak = level
    gain = min(_TARGET_DB - mean, _PEAK_DB - peak)
    if abs(gain) < 0.5:
        return
    louder = path.with_name(f"{path.stem}_level.wav")
    result = run_proc(["ffmpeg", "-y", "-i", str(path), "-af", f"volume={gain:.2f}dB",
                       *_WAV, str(louder)], timeout=60)
    if result.returncode == 0 and louder.exists():
        louder.replace(path)


def _silence(path: Path, seconds: float) -> None:
    run_proc(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", f"{seconds:.2f}", *_WAV, str(path)],
        timeout=60,
    )


def join(pieces: List[bytes], note: str = "") -> Tuple[bytes, float]:
    """One MP3 out of many, with a gap between the contributions that fits the moment.

    Re-encoded on purpose: the pieces come from different voices and may carry
    different bitrates, and only a fresh encode gives a correct running time.
    ``note`` is written into the metadata comment of the file.
    """
    usable = [s for s in pieces if s]
    if not usable:
        raise AudioError("no voiced contribution available")
    ffmpeg_path()

    with tempfile.TemporaryDirectory(prefix="podcast_") as tmpdir:
        folder = Path(tmpdir)
        parts: List[Tuple[Path, float]] = []
        for i, piece in enumerate(usable):
            raw = folder / f"raw_{i:03d}.mp3"
            raw.write_bytes(piece)
            wav = folder / f"part_{i:03d}.wav"
            seconds = _as_wav(raw, wav)
            _level_out(wav)
            parts.append((wav, seconds))

        pauses = {}
        lines: List[str] = []
        for i, (wav, seconds) in enumerate(parts):
            if i:
                pause = pause_before(parts[i - 1][1], seconds)
                if pause not in pauses:
                    pauses[pause] = folder / f"pause_{len(pauses)}.wav"
                    _silence(pauses[pause], pause)
                lines.append(f"file '{pauses[pause]}'")
            lines.append(f"file '{wav}'")
        listing = folder / "parts.txt"
        listing.write_text("\n".join(lines) + "\n")

        target = folder / "podcast.mp3"
        result = run_proc(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-q:a", "4",
             *(["-metadata", f"comment={note}"] if note else []), str(target)],
            timeout=900,
        )
        if result.returncode != 0 or not target.exists():
            logger.error("joining the podcast failed (rc=%s): %s",
                         result.returncode, result.stderr[-400:])
            raise AudioError(f"joining failed: {result.stderr[-200:]}")
        return target.read_bytes(), audio_duration(target)
