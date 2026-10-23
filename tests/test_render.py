import pytest

from conftest import needs_ffmpeg
from doc2podcast import make_podcast, markdown, render
from doc2podcast.audio import pause_before
from doc2podcast.config import resolve
from doc2podcast.errors import ConfigError, ModelError
from doc2podcast.limits import PAUSES
from doc2podcast.schemas import Line, Person, PodcastParams

SCRIPT = """# Podcast script

## Cast

- Ana (host, voice alloy)
- Ben (expert, voice echo)

## Settings

- Language: en
- Style: teaching
- Speed: 0.9

## Conversation

**Ana:** Hello and welcome to the episode.

**Ben:** Good to be here, let us start.

**Ana:** So what does the material say?
"""


def speech_conf(conf):
    return {k: v for k, v in conf.items() if k not in ("model",)}


def _no_sleep(seconds):
    raise AssertionError("a final error must not be waited out")


@needs_ffmpeg
def test_a_script_becomes_one_mp3(server, conf, tmp_path):
    target = render(SCRIPT, tmp_path / "out.mp3", **speech_conf(conf))
    assert target.exists() and target.stat().st_size > 0
    assert len(server.speech_requests) == 3


@needs_ffmpeg
def test_without_an_output_the_bytes_come_back(server, conf):
    audio = render(SCRIPT, **speech_conf(conf))
    assert isinstance(audio, bytes) and audio


@needs_ffmpeg
def test_every_contribution_is_spoken_once_with_its_own_voice(server, conf):
    render(SCRIPT, **speech_conf(conf))
    bodies = [r["body"] for r in server.speech_requests]
    assert [b["voice"] for b in bodies] == ["alloy", "echo", "alloy"]
    assert bodies[0]["input"].startswith("Hello and welcome")
    assert all(b["model"] == "speech-model" for b in bodies)


@needs_ffmpeg
def test_a_script_that_names_its_voices_needs_none_on_the_call(server, conf):
    options = {k: v for k, v in speech_conf(conf).items() if k != "voices"}
    render(SCRIPT, **options)
    assert [r["body"]["voice"] for r in server.speech_requests] == ["alloy", "echo", "alloy"]


def test_a_script_without_voices_anywhere_says_so(server, conf):
    bare = SCRIPT.replace(" (host, voice alloy)", " (host)").replace(" (expert, voice echo)",
                                                                     " (expert)")
    options = {k: v for k, v in speech_conf(conf).items() if k != "voices"}
    with pytest.raises(ConfigError) as info:
        render(bare, **options)
    assert "2 voices" in str(info.value)


@needs_ffmpeg
def test_the_voices_of_the_call_beat_those_in_the_script(server, conf):
    render(SCRIPT, **dict(speech_conf(conf), voices="nova,fable"))
    assert [r["body"]["voice"] for r in server.speech_requests] == ["nova", "fable", "nova"]


@needs_ffmpeg
def test_the_speed_of_the_script_is_used(server, conf):
    render(SCRIPT, **speech_conf(conf))
    assert server.speech_requests[0]["body"]["speed"] == 0.9


@needs_ffmpeg
def test_an_intro_note_is_spoken_first(server, conf):
    render(SCRIPT, intro_note="This episode was made with a model.", **speech_conf(conf))
    assert len(server.speech_requests) == 4
    assert server.speech_requests[0]["body"]["input"].startswith("This episode was made")


@needs_ffmpeg
def test_progress_counts_the_contributions(server, conf):
    seen = []
    render(SCRIPT, progress=lambda done, total: seen.append((done, total)), **speech_conf(conf))
    assert seen == [(1, 3), (2, 3), (3, 3)]


@needs_ffmpeg
def test_a_stumbling_provider_is_tried_again(server, conf, monkeypatch):
    from doc2podcast import voicing as module

    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    server.speech_failures = 1
    audio = render(SCRIPT, **speech_conf(conf))
    assert audio


def test_a_dead_provider_costs_one_ladder_and_no_more(server, conf, monkeypatch):
    """Four attempts for the first contribution, then the run stops."""
    from doc2podcast import voicing as module

    slept = []
    monkeypatch.setattr(module.time, "sleep", slept.append)
    server.fail = True
    with pytest.raises(ModelError) as info:
        render(SCRIPT, **speech_conf(conf))
    assert len(server.speech_requests) == module.ATTEMPTS == 4
    assert slept == list(module.RETRY_PAUSES)
    assert "Contribution 1" in str(info.value)


def test_a_refused_key_is_not_tried_again(server, conf, monkeypatch):
    from doc2podcast import voicing as module

    monkeypatch.setattr(module.time, "sleep", _no_sleep)
    server.fail, server.fail_status = True, 401
    with pytest.raises(ModelError) as info:
        render(SCRIPT, **speech_conf(conf))
    assert len(server.speech_requests) == 1
    assert "401" in str(info.value)


def test_an_unknown_voice_is_not_tried_again(server, conf, monkeypatch):
    from doc2podcast import voicing as module

    monkeypatch.setattr(module.time, "sleep", _no_sleep)
    server.fail, server.fail_status = True, 400
    with pytest.raises(ModelError):
        render(SCRIPT, **speech_conf(conf))
    assert len(server.speech_requests) == 1


def test_a_busy_provider_is_tried_again(server, conf, monkeypatch):
    """429 is worth a second try, unlike 400 and 401."""
    from doc2podcast import voicing as module

    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    server.speech_failures, server.speech_status = 1, 429
    render(SCRIPT, **speech_conf(conf))
    assert len(server.speech_requests) == 4


def test_the_time_budget_ends_the_voicing(server, conf):
    from doc2podcast.errors import LimitError
    from doc2podcast.voicing import StageClock, voice_lines

    settings = resolve(**dict(speech_conf(conf), base_url=server.base_url))
    lines, params = markdown.from_markdown(SCRIPT)
    with pytest.raises(LimitError) as info:
        voice_lines(None, settings, lines, params, clock=StageClock(0))
    assert server.speech_requests == []
    assert "gave up after" in str(info.value)


def test_the_budget_can_be_turned_off(conf):
    from doc2podcast.voicing import clock_for

    assert clock_for(resolve(**dict(speech_conf(conf), stage_seconds=0))) is None
    assert clock_for(resolve(**speech_conf(conf))) is not None


def test_a_contribution_without_a_voice_says_which_one(server, conf):
    from doc2podcast.voicing import voice_lines

    settings = resolve(**dict(speech_conf(conf), base_url=server.base_url))
    lines, params = markdown.from_markdown(SCRIPT)
    params.persons[1].voice_id = ""
    with pytest.raises(ConfigError) as info:
        voice_lines(None, settings, lines, params)
    assert "Contribution 2 has no voice" in str(info.value)


def test_four_at_a_time_keep_the_order_of_the_script(conf, monkeypatch):
    """The early contributions take longest, the pieces still come back in order."""
    import time as clock_module

    from doc2podcast import voicing as module

    long_script = SCRIPT + "".join(
        "\n**%s:** Contribution %s of the conversation.\n"
        % (("Ana", "Ben")[i % 2], word)
        for i, word in enumerate(("four", "five", "six", "seven", "eight"))
    )
    lines, params = markdown.from_markdown(long_script)
    order = {line.text: i for i, line in enumerate(lines)}

    def slow(client, settings, text, voice, language, speed):
        clock_module.sleep(0.02 * (len(lines) - order[text]))
        return text.encode()

    monkeypatch.setattr(module, "speak_line", slow)
    settings = resolve(**dict(speech_conf(conf), concurrency=4))
    pieces = module.voice_lines(None, settings, lines, params)
    assert [p.decode() for p in pieces] == [line.text for line in lines]


@needs_ffmpeg
def test_a_long_contribution_goes_out_in_parts(server, conf):
    long_line = "This sentence carries the material. " * 30
    script = SCRIPT.replace("Hello and welcome to the episode.", long_line.strip())
    render(script, **speech_conf(conf))
    assert len(server.speech_requests) == 5
    assert all(len(r["body"]["input"]) <= 400 for r in server.speech_requests)


@needs_ffmpeg
def test_the_speech_library_reads_no_environment_of_its_own(server, conf, monkeypatch):
    monkeypatch.setenv("DOC2SPEECH_MAX_CHARS_PER_CHUNK", "20")
    monkeypatch.setenv("DOC2SPEECH_CONCURRENCY", "16")
    render(SCRIPT, **speech_conf(conf))
    assert len(server.speech_requests) == 3


def test_a_script_without_a_speech_model_says_so():
    with pytest.raises(ConfigError) as info:
        render(SCRIPT, base_url="http://x/v1", voices="a,b")
    assert "tts_model" in str(info.value)


def test_a_script_with_too_few_voices_says_so(server, conf):
    bare = SCRIPT.replace(", voice alloy", "").replace(", voice echo", "")
    with pytest.raises(ConfigError) as info:
        render(bare, **dict(speech_conf(conf), voices="alloy"))
    assert "2 voices (--voices or DOC2PODCAST_VOICES), 1 given" in str(info.value)


@needs_ffmpeg
def test_one_run_writes_the_script_and_voices_it(server, conf, material, tmp_path):
    target = make_podcast([material], tmp_path / "out.mp3", minutes=5, **conf)
    assert target.exists()
    assert len(server.speech_requests) == 27
    assert len(server.chat_requests) == 2


def test_one_run_checks_the_speech_side_before_writing(server, conf, material):
    broken = dict(conf)
    broken.pop("tts_model")
    with pytest.raises(ConfigError):
        make_podcast([material], minutes=5, **broken)
    assert server.chat_requests == []


def test_the_gap_fits_the_moment():
    quick, normal, long_gap = PAUSES
    assert pause_before(5.0, 1.0) == quick
    assert pause_before(20.0, 5.0) == long_gap
    assert pause_before(5.0, 5.0) == normal


def test_the_cast_of_a_script_decides_who_speaks():
    lines, params = markdown.from_markdown(SCRIPT)
    assert len(lines) == 3
    assert [p.voice_id for p in params.persons] == ["alloy", "echo"]
    assert isinstance(params, PodcastParams)
    assert isinstance(params.persons[0], Person)
    assert isinstance(lines[0], Line)


def test_a_missing_ffmpeg_says_what_to_install(monkeypatch):
    from doc2podcast import audio
    from doc2podcast.errors import AudioError

    monkeypatch.setattr(audio.shutil, "which", lambda name: None)
    with pytest.raises(AudioError) as info:
        audio.ffmpeg_path()
    assert "ffmpeg was not found" in str(info.value)
    assert "apt install ffmpeg" in str(info.value)
    with pytest.raises(AudioError) as probe:
        audio.ffprobe_path()
    assert "ffprobe was not found" in str(probe.value)


@needs_ffmpeg
def test_the_environment_decides_for_a_script_without_a_head(server, conf, monkeypatch):
    """A hand written script carries no settings, so the environment keeps its say."""
    monkeypatch.setenv("DOC2PODCAST_LANGUAGE", "de")
    monkeypatch.setenv("DOC2PODCAST_SPEED", "1.1")
    render("Ana: Es sind 3 Tage.\n\nBen: Genau 3 Tage.\n", **speech_conf(conf))
    body = server.speech_requests[0]["body"]
    assert body["speed"] == 1.1
    # German text keeps its digits, only English spells them out.
    assert "3" in body["input"] and "three" not in body["input"]


@needs_ffmpeg
def test_the_head_of_the_script_beats_the_environment(server, conf, monkeypatch):
    monkeypatch.setenv("DOC2PODCAST_LANGUAGE", "de")
    monkeypatch.setenv("DOC2PODCAST_SPEED", "1.1")
    script = SCRIPT.replace("Hello and welcome to the episode.", "It is 3 days.")
    render(script, **speech_conf(conf))
    body = server.speech_requests[0]["body"]
    assert body["speed"] == 0.9
    assert "three days" in body["input"]
