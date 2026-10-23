import json

import pytest

from doc2podcast import script
from doc2podcast.errors import ScriptUnusable
from doc2podcast.limits import MAX_LINE_CHARS, MAX_LINES
from doc2podcast.schemas import Line, Person, PodcastParams, length_plan


def params(count=2, language="en", **extra):
    people = [Person(name=n, role=r) for n, r in
              list(zip(["Ana", "Ben", "Cleo", "Dan"], ["host", "expert", "student", "critic"]))[:count]]
    return PodcastParams(persons=people, language=language, **extra)


def test_minutes_become_contributions():
    assert length_plan(5)[0] == 27
    assert length_plan(10)[0] == 54
    assert length_plan(20)[0] == 107


def test_a_very_long_wish_stops_at_the_limit():
    assert length_plan(600)[0] == MAX_LINES


def test_the_parts_share_the_contributions():
    assert script.part_lengths(54, 2) == [27, 27]
    assert script.part_lengths(10, 3) == [4, 3, 3]
    assert sum(script.part_lengths(107, 4)) == 107


def test_more_parts_than_contributions_shrink():
    assert script.part_lengths(2, 5) == [1, 1]


def test_the_prompt_names_cast_style_and_length():
    messages = script.build_messages("MATERIAL", params(), count=12)
    user = messages[1]["content"]
    assert "0: Ana (host" in user and "1: Ben (expert" in user
    assert "exactly 12 contributions" in user
    assert "explanatory and vivid" in user
    assert "MATERIAL" in user


def test_the_german_prompt_is_german():
    user = script.build_messages("MATERIAL", params(language="de"), count=8)[1]["content"]
    assert "genau 8 Beiträge" in user
    assert "Sprache des Skripts: Deutsch" in user


def test_one_speaker_gets_no_conversation_rules():
    user = script.build_messages("MATERIAL", params(count=1), count=8)[1]["content"]
    assert "Only one person speaks" in user
    assert "nobody speaks twice in a row" not in user


def test_a_middle_part_neither_greets_nor_says_goodbye():
    user = script.build_messages("M", params(), count=8, part=2, parts=3,
                                 plan="1. a\n2. b\n3. c")[1]["content"]
    assert "no greeting and no goodbye" in user
    assert "part 2 of 3" in user


def test_the_last_part_says_goodbye_and_carries_the_thread():
    user = script.build_messages("M", params(), count=8, part=3, parts=3,
                                 thread="One rule, many questions.")[1]["content"]
    assert "The last contribution says goodbye" in user
    assert "One rule, many questions." in user


def test_what_came_before_is_shown_and_the_speaker_changes():
    before = [Line(speaker=1, text="Something said earlier.")]
    user = script.build_messages("M", params(), count=8, so_far=before)[1]["content"]
    assert "Said last so far" in user
    assert "Ben: Something said earlier." in user
    assert "was by speaker 1" in user


def test_covered_subjects_are_not_repeated():
    user = script.build_messages("M", params(), count=8,
                                 covered=["an earlier subject"])[1]["content"]
    assert "Already covered, do not repeat" in user
    assert "- an earlier subject" in user


def test_the_plan_prompt_asks_for_the_number_of_parts():
    system = script.plan_messages("M", params(), 3, ["a.pdf", "b.pdf"])[0]["content"]
    assert "exactly 3 consecutive parts" in system
    assert "a.pdf, b.pdf" in system


def test_parse_plan_reads_title_gist_opening_and_thread():
    raw = json.dumps({"opening": "A story.", "thread": "A thought.",
                      "parts": [{"title": "One", "gist": "First refs: [1-2]"},
                                {"title": "Two", "gist": "Second"}]})
    plan = script.parse_plan(raw, 2)
    assert [p["title"] for p in plan] == ["One", "Two"]
    assert plan[0]["gist"] == "First"
    assert plan[0]["opening"] == "A story."
    assert plan[-1]["thread"] == "A thought."


def test_parse_plan_folds_too_many_parts():
    raw = json.dumps({"parts": [{"title": str(i), "gist": "g"} for i in range(5)]})
    plan = script.parse_plan(raw, 2)
    # The first parts stay, the surplus ones are dropped from the back.
    assert [p["title"] for p in plan] == ["0", "1"]


def test_a_folded_part_leaves_its_files_with_the_one_before_it():
    raw = json.dumps({"parts": [
        {"title": "One", "gist": "g", "files": ["a.pdf"]},
        {"title": "Two", "gist": "g", "files": ["b.pdf"]},
        {"title": "Three", "gist": "g", "files": ["c.pdf", "a.pdf"]},
    ]})
    plan = script.parse_plan(raw, 2, ["a.pdf", "b.pdf", "c.pdf"])
    assert [p["title"] for p in plan] == ["One", "Two"]
    assert plan[1]["files"] == ["b.pdf", "c.pdf", "a.pdf"]


def test_a_plan_keeps_only_the_files_that_exist():
    raw = json.dumps({"parts": [{"title": "One", "gist": "g",
                                 "files": ["A.pdf", "made-up.pdf", "a.pdf", 7]}]})
    plan = script.parse_plan(raw, 1, ["a.pdf", "b.pdf"])
    assert plan[0]["files"] == ["a.pdf"]


def test_the_plan_prompt_asks_for_the_files_of_a_part():
    params = PodcastParams(persons=[Person(name="Ana")])
    system = script.plan_messages("M", params, 2, ["a.pdf", "b.pdf"])[0]["content"]
    assert '"files": ["..."]' in system
    one = script.plan_messages("M", params, 2, ["a.pdf"])[0]["content"]
    assert "files" not in one


def test_a_second_plan_names_the_files_that_got_too_little_room():
    params = PodcastParams(persons=[Person(name="Ana")])
    task = script.plan_messages("M", params, 2, ["a.pdf", "b.pdf"],
                                ["b.pdf (70 % of the material)"])[1]["content"]
    assert "FAR TOO LITTLE ROOM" in task
    assert "b.pdf (70 % of the material)" in task


def test_parse_plan_refuses_a_plan_without_parts():
    with pytest.raises(ScriptUnusable):
        script.parse_plan('{"parts": []}', 2)
    with pytest.raises(ScriptUnusable):
        script.parse_plan("no json here", 2)


def test_parse_answer_reads_the_contributions():
    raw = json.dumps({"lines": [{"speaker": 0, "text": "One."}, {"speaker": 1, "text": "Two."}]})
    lines = script.parse_answer(raw, 2)
    assert [l.speaker for l in lines] == [0, 1]
    assert [l.text for l in lines] == ["One.", "Two."]


def test_parse_answer_takes_json_out_of_a_fence():
    raw = '```json\n{"lines": [{"speaker": 0, "text": "One."}, {"speaker": 1, "text": "Two."}]}\n```'
    assert len(script.parse_answer(raw, 2)) == 2


def test_a_stray_speaker_wraps_instead_of_collapsing():
    raw = json.dumps({"lines": [{"speaker": 7, "text": "One."}, {"speaker": 5, "text": "Two."}]})
    assert [l.speaker for l in script.parse_answer(raw, 3)] == [1, 2]


def test_a_too_long_contribution_is_cut():
    raw = json.dumps({"lines": [{"speaker": 0, "text": "x" * (MAX_LINE_CHARS + 500)},
                                {"speaker": 1, "text": "Two."}]})
    assert len(script.parse_answer(raw, 2)[0].text) == MAX_LINE_CHARS


def test_an_answer_with_one_voice_is_refused_when_two_are_cast():
    raw = json.dumps({"lines": [{"speaker": 0, "text": "One."}, {"speaker": 0, "text": "Two."}]})
    with pytest.raises(ScriptUnusable):
        script.parse_answer(raw, 2)


def test_one_cast_voice_may_speak_alone():
    raw = json.dumps({"lines": [{"speaker": 0, "text": "One."}, {"speaker": 0, "text": "Two."}]})
    assert len(script.parse_answer(raw, 1)) == 2


def test_an_answer_with_too_few_contributions_is_refused():
    with pytest.raises(ScriptUnusable):
        script.parse_answer(json.dumps({"lines": [{"speaker": 0, "text": "One."}]}), 2)
    with pytest.raises(ScriptUnusable):
        script.parse_answer("{}", 2)
    with pytest.raises(ScriptUnusable):
        script.parse_answer("not json", 2)


def test_a_speaker_never_addresses_themselves():
    lines = [Line(speaker=0, text="Ana, that is right."), Line(speaker=1, text="I agree, Ana.")]
    out = script.without_self_address(lines, ["Ana", "Ben"])
    assert out[0].text == "That is right."
    assert out[1].text == "I agree, Ana."
