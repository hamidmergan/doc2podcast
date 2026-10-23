import pytest

from doc2podcast import config
from doc2podcast.errors import ConfigError


def test_nothing_is_required_to_resolve():
    settings = config.resolve()
    assert settings.base_url is None and settings.model is None
    assert settings.api_key == config.PLACEHOLDER_API_KEY


def test_the_chat_side_names_what_is_missing():
    with pytest.raises(ConfigError) as info:
        config.require_chat(config.resolve())
    assert "DOC2PODCAST_BASE_URL" in str(info.value)
    assert "DOC2PODCAST_MODEL" in str(info.value)


def test_the_speech_side_names_what_is_missing():
    settings = config.resolve(base_url="http://x/v1", model="m")
    with pytest.raises(ConfigError) as info:
        config.require_tts(settings, 2)
    assert "DOC2PODCAST_TTS_MODEL" in str(info.value)
    assert "2 voices" in str(info.value)


def test_the_speech_side_falls_back_to_the_chat_server():
    settings = config.resolve(base_url="http://chat/v1", model="m", api_key="k")
    assert settings.tts_base_url == "http://chat/v1"
    assert settings.tts_api_key == "k"


def test_the_speech_side_may_have_its_own_server():
    settings = config.resolve(base_url="http://chat/v1", model="m", api_key="k",
                              tts_base_url="http://voice/v1", tts_api_key="v")
    assert settings.tts_base_url == "http://voice/v1"
    assert settings.tts_api_key == "v"


def test_environment_variables_are_read(monkeypatch):
    monkeypatch.setenv("DOC2PODCAST_BASE_URL", "http://env/v1")
    monkeypatch.setenv("DOC2PODCAST_MODEL", "env-model")
    monkeypatch.setenv("DOC2PODCAST_TTS_MODEL", "env-speech")
    monkeypatch.setenv("DOC2PODCAST_VOICES", "a, b ,c")
    monkeypatch.setenv("DOC2PODCAST_MINUTES", "7")
    settings = config.resolve()
    assert settings.base_url == "http://env/v1"
    assert settings.model == "env-model"
    assert settings.tts_model == "env-speech"
    assert settings.voices == ("a", "b", "c")
    assert settings.minutes == 7


def test_an_argument_beats_the_environment(monkeypatch):
    monkeypatch.setenv("DOC2PODCAST_MODEL", "env-model")
    assert config.resolve(model="given").model == "given"


def test_the_openai_key_is_the_last_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert config.resolve().api_key == "sk-test"


def test_a_broken_environment_value_says_which_one(monkeypatch):
    monkeypatch.setenv("DOC2PODCAST_MINUTES", "soon")
    with pytest.raises(ConfigError) as info:
        config.resolve()
    assert "DOC2PODCAST_MINUTES" in str(info.value)


def test_voices_may_be_a_list_or_a_string():
    assert config.resolve(voices="a,b").voices == ("a", "b")
    assert config.resolve(voices=["a", "b"]).voices == ("a", "b")


def test_the_number_of_speakers_follows_the_voices():
    assert config.resolve(voices="a,b,c").speakers == 3
    assert config.resolve().speakers == 2


@pytest.mark.parametrize("bad", [
    {"language": "fr"},
    {"style": "funny"},
    {"speakers": 9},
    {"speed": 3.0},
    {"minutes": 0.1},
    {"max_chars": 0},
    {"max_retries": -1},
])
def test_an_impossible_setting_is_refused(bad):
    with pytest.raises(ConfigError):
        config.resolve(**bad)


def test_two_speakers_may_not_share_a_voice():
    settings = config.resolve(base_url="http://x/v1", model="m", tts_model="t",
                              voices="alloy,alloy")
    with pytest.raises(ConfigError) as info:
        config.require_tts(settings, 2)
    assert "voice of their own" in str(info.value)
