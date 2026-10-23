import pytest

from doc2podcast import markdown, write_script
from doc2podcast.errors import ConfigError, LimitError, ModelError


def test_a_script_comes_back_as_markdown(server, conf, material):
    text = write_script([material], minutes=5, **conf)
    assert text.startswith("# Podcast script")
    lines, params = markdown.from_markdown(text)
    assert len(lines) == 27
    assert [p.name for p in params.persons] == ["Ana", "Ben"]


def test_the_speakers_take_turns(server, conf, material):
    lines, _ = markdown.from_markdown(write_script([material], minutes=5, **conf))
    speakers = [l.speaker for l in lines]
    assert set(speakers) == {0, 1}
    assert all(a != b for a, b in zip(speakers, speakers[1:]))


def test_a_longer_episode_has_more_contributions(server, conf, material):
    short = markdown.from_markdown(write_script([material], minutes=5, **conf))[0]
    long = markdown.from_markdown(write_script([material], minutes=20, **conf))[0]
    assert len(short) == 27 and len(long) == 107


def test_a_long_episode_is_written_in_several_calls(server, conf, material):
    write_script([material], minutes=20, **conf)
    # One plan and four parts, because 107 contributions need four calls of 27.
    assert len(server.chat_requests) == 5


def test_a_short_episode_needs_one_plan_and_one_part(server, conf, material):
    write_script([material], minutes=5, **conf)
    assert len(server.chat_requests) == 2


def test_the_material_reaches_the_model(server, conf, material):
    write_script([material], minutes=5, **conf)
    user = server.chat_requests[-1]["body"]["messages"][1]["content"]
    assert "A landlord may keep only what the damage costs." in user
    assert "[paper.md, p. 1]" in user


def test_names_roles_and_language_reach_the_prompt(server, conf, material):
    write_script([material], minutes=5, names="Mia,Noah", roles="host,critic",
                 language="de", **conf)
    user = server.chat_requests[-1]["body"]["messages"][1]["content"]
    assert "0: Mia (Moderation" in user
    assert "1: Noah (Kritische Stimme" in user


def test_one_speaker_writes_a_monologue(server, conf, material):
    server.persons = 1
    text = write_script([material], minutes=5, speakers=1, **conf)
    lines, params = markdown.from_markdown(text)
    assert len(params.persons) == 1
    assert {l.speaker for l in lines} == {0}


def test_an_instruction_is_classified_once(server, conf, material):
    write_script([material], minutes=5, instructions="keep it simple", **conf)
    systems = [r["body"]["messages"][0]["content"] for r in server.chat_requests]
    assert sum("instruction for" in s for s in systems) == 1
    user = server.chat_requests[-1]["body"]["messages"][1]["content"]
    assert "INSTRUCTION FROM THE TEACHER: \"keep it simple\"" in user


def test_a_run_without_an_instruction_asks_no_classifier(server, conf, material):
    write_script([material], minutes=5, **conf)
    systems = [r["body"]["messages"][0]["content"] for r in server.chat_requests]
    assert not any("instruction for" in s for s in systems)


def test_the_json_mode_is_used_and_dropped_when_refused(server, conf, material):
    write_script([material], minutes=5, **conf)
    assert server.chat_requests[0]["body"].get("response_format") == {"type": "json_object"}

    server.refuse_json_mode = True
    server.requests.clear()
    write_script([material], minutes=5, **conf)
    assert server.chat_requests[-1]["body"].get("response_format") is None


def test_a_missing_chat_setting_is_named(material):
    with pytest.raises(ConfigError) as info:
        write_script([material], minutes=5)
    assert "base_url" in str(info.value)


def test_a_broken_server_is_reported(server, conf, material):
    server.fail = True
    with pytest.raises(ModelError):
        write_script([material], minutes=5, **conf)


def test_too_many_files_are_refused(server, conf, tmp_path):
    paths = []
    for index in range(4):
        path = tmp_path / ("a%d.txt" % index)
        path.write_text("Some material about the matter.", encoding="utf-8")
        paths.append(path)
    with pytest.raises(LimitError):
        write_script(paths, minutes=5, max_sources=3, **conf)


def test_without_a_file_nothing_is_written(server, conf):
    from doc2podcast.errors import EmptyTextError

    with pytest.raises(EmptyTextError):
        write_script([], minutes=5, **conf)


def test_progress_counts_the_parts(server, conf, material):
    seen = []
    write_script([material], minutes=20, progress=lambda done, total: seen.append((done, total)),
                 **conf)
    assert seen[0] == (0, 4) and seen[-1] == (4, 4)
