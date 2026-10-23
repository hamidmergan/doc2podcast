import subprocess
import sys
from pathlib import Path

import doc2podcast
from doc2podcast import client, instructions
from doc2podcast.config import Settings

ROOT = Path(__file__).resolve().parent.parent


def test_the_package_exports_the_three_functions():
    for name in ("write_script", "render", "make_podcast"):
        assert callable(getattr(doc2podcast, name))
    assert doc2podcast.__version__ == "0.1.0"


def test_the_version_matches_the_project_file():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "%s"' % doc2podcast.__version__ in text


def test_the_command_is_installed():
    out = subprocess.run([sys.executable, "-m", "doc2podcast.cli", "--version"],
                         capture_output=True, text=True)
    assert out.returncode == 0
    assert "doc2podcast" in out.stdout


def test_the_timeout_survives_a_missing_http_library(monkeypatch):
    monkeypatch.setattr(client.importlib, "import_module",
                        lambda name: (_ for _ in ()).throw(ImportError(name)))
    assert client._timeout(300) == 300


def test_the_timeout_keeps_its_values():
    timeout = client._timeout(300)
    assert timeout == 300 or timeout.read == 300


def test_a_speech_client_uses_the_speech_side():
    settings = Settings(
        base_url="http://chat/v1", model="m", api_key="k",
        tts_base_url="http://voice/v1", tts_model="t", tts_api_key="v",
        voices=("a",), names=(), roles=(), speakers=1, minutes=5.0, language="en",
        style="teaching", speed=0.9, instructions="", intro_note="", max_chars=100,
        max_sources=1, concurrency=1, timeout=10.0, max_retries=0, temperature=0.4,
    )
    made = client.make_speech_client(settings)
    assert str(made.base_url).rstrip("/") == "http://voice/v1"


def test_an_instruction_is_cleaned_to_one_line():
    assert instructions.clean("  keep\n it   short ") == "keep it short"
    assert instructions.clean(None) == ""


def test_the_way_is_read_out_of_the_answer():
    assert instructions.read_way('{"way": "topic"}') == instructions.TOPIC
    assert instructions.read_way('<think>hm</think>{"way": "nonsense"}') == instructions.NONSENSE
    assert instructions.read_way("nothing usable") == instructions.MANNER
    assert instructions.read_way(None) == instructions.MANNER


def test_a_dropped_instruction_reaches_no_call():
    assert instructions.drops_out(instructions.IGNORED)
    assert instructions.drops_out(instructions.NONSENSE)
    assert instructions.write_addition("about the deposit", instructions.IGNORED) == ""
    assert instructions.plan_addition("about the deposit", instructions.NONSENSE, "part") == ""


def test_a_topic_narrows_the_plan():
    assert instructions.focus("the deposit", instructions.TOPIC)
    assert not instructions.focus("the deposit", instructions.MANNER)
    text = instructions.plan_addition("the deposit", instructions.TOPIC, "part")
    assert "Plan every part around" in text


def test_a_manner_only_shapes_the_result():
    text = instructions.plan_addition("keep it short", instructions.MANNER, "part")
    assert "only says how the result should be" in text


def test_a_lost_classification_counts_as_a_manner():
    def broken(messages):
        raise RuntimeError("server gone")

    assert instructions.decide(broken, "x", "material", "a podcast") == instructions.MANNER
