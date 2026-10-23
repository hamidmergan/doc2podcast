import pytest

from doc2podcast import markdown
from doc2podcast.errors import ScriptUnusable
from doc2podcast.schemas import Line, Person, PodcastParams


def params(**extra):
    base = dict(
        persons=[Person(name="Ana", role="host", voice_id="alloy"),
                 Person(name="Ben", role="expert", voice_id="echo")],
        language="en",
    )
    base.update(extra)
    return PodcastParams(**base)


LINES = [Line(speaker=0, text="Hello and welcome."), Line(speaker=1, text="Good to be here.")]


def test_the_script_names_cast_settings_and_contributions():
    text = markdown.to_markdown(LINES, params())
    assert "## Cast" in text and "## Conversation" in text
    assert "- Ana (host, voice alloy)" in text
    assert "**Ana:** Hello and welcome." in text
    assert "- Language: en" in text


def test_a_script_reads_back_into_what_it_was_written_from():
    text = markdown.to_markdown(LINES, params(speed=1.1, intro_note="A note."))
    lines, back = markdown.from_markdown(text)
    assert [(l.speaker, l.text) for l in lines] == [(0, "Hello and welcome."),
                                                    (1, "Good to be here.")]
    assert [(p.name, p.role, p.voice_id) for p in back.persons] == [
        ("Ana", "host", "alloy"), ("Ben", "expert", "echo")]
    assert back.speed == 1.1
    assert back.intro_note == "A note."


def test_a_hand_written_script_needs_no_head():
    lines, back = markdown.from_markdown("Ana: One.\n\nBen: Two.\n\nAna: Three.\n")
    assert [l.speaker for l in lines] == [0, 1, 0]
    assert [p.name for p in back.persons] == ["Ana", "Ben"]
    assert [p.role for p in back.persons] == ["host", "expert"]


def test_bold_names_are_read_in_both_shapes():
    lines, _ = markdown.from_markdown("**Ana:** One.\n\n**Ben**: Two.\n")
    assert [l.text for l in lines] == ["One.", "Two."]


def test_a_script_without_a_contribution_is_refused():
    with pytest.raises(ScriptUnusable):
        markdown.from_markdown("# Podcast script\n\nNothing here.\n")


def test_the_transcript_puts_the_name_in_front():
    assert markdown.transcript(LINES, params()) == (
        "Ana: Hello and welcome.\n\nBen: Good to be here.\n")


def test_a_german_script_keeps_its_language():
    text = markdown.to_markdown(LINES, params(language="de"))
    assert markdown.from_markdown(text)[1].language == "de"
