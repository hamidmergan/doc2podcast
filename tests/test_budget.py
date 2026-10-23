"""The material has to fit the window of the chat model, every call again."""

import pytest

from doc2podcast import budget, write_script
from doc2podcast.errors import ConfigError, ModelError
from doc2podcast.limits import MIN_WINDOW_TOKENS

# A window that carries about 28,000 characters of material.
SMALL_WINDOW = 16_384


def big_material(tmp_path, chars=60_000):
    path = tmp_path / "rules.md"
    sentence = "A tenant may ask for the heating bill of the past year. "
    path.write_text("# Rules\n\n" + sentence * (chars // len(sentence)), encoding="utf-8")
    return path


def test_the_window_decides_how_much_text_one_call_carries():
    # The task and the answer take 7,000 tokens of the window, the rest carries
    # material at three characters a token.
    assert budget.window_chars(SMALL_WINDOW) == 28_152
    assert budget.window_chars(131_072) == 372_216
    assert budget.window_chars(131_072) > budget.window_chars(SMALL_WINDOW) > 0


def test_a_window_too_small_for_an_episode_is_refused():
    with pytest.raises(ConfigError) as info:
        budget.window_chars(4096)
    assert "DOC2PODCAST_CONTEXT_WINDOW" in str(info.value)
    assert str(MIN_WINDOW_TOKENS) in str(info.value)


def test_the_smallest_accepted_window_is_sixteen_thousand_tokens():
    assert MIN_WINDOW_TOKENS == 16_384
    assert budget.window_chars(MIN_WINDOW_TOKENS) > 0
    with pytest.raises(ConfigError):
        budget.window_chars(MIN_WINDOW_TOKENS - 1)


def test_material_that_fits_goes_out_unchanged(server, conf, material):
    write_script([material], minutes=5, **conf)
    assert server.topic_requests == []
    user = str(server.plan_requests[0]["body"]["messages"])
    assert "A landlord may keep only what the damage costs" in user


def test_material_larger_than_the_window_is_told_through_its_topics(server, conf, tmp_path):
    path = big_material(tmp_path)
    write_script([path], minutes=5, context_window=SMALL_WINDOW, **conf)
    assert len(server.topic_requests) == 4
    for request in server.chat_requests:
        body = str(request["body"]["messages"])
        if "You map a text" in body:
            continue
        assert "Topic 1: What topic 1 states." in body
        assert len(body) < budget.window_chars(SMALL_WINDOW) + 5000


def test_the_topics_are_read_once_for_the_whole_episode(server, conf, tmp_path):
    path = big_material(tmp_path)
    write_script([path], minutes=20, context_window=SMALL_WINDOW, **conf)
    # Four part calls and one plan call, and the topics only once before them.
    assert len(server.topic_requests) == 4
    assert len(server.chat_requests) == 4 + 1 + 4


def test_a_piece_whose_topics_are_lost_costs_its_topics_only(server, conf, tmp_path):
    asked = []

    def ask(messages):
        asked.append(messages)
        if len(asked) == 1:
            raise ModelError("the server said no")
        return '{"topics": [{"title": "Kept", "gist": "Still there."}]}'

    small = budget.Budget(ask, "en", "a test", SMALL_WINDOW)
    out = small.fit("block\n\n" * 20_000)
    assert "Kept" in out and len(asked) > 1


def test_no_topic_at_all_is_an_error():
    def ask(messages):
        return "nothing usable"

    small = budget.Budget(ask, "en", "a test", SMALL_WINDOW)
    with pytest.raises(ModelError) as info:
        small.fit("block\n\n" * 20_000)
    assert "--max-chars" in str(info.value)


def test_the_pieces_are_cut_at_block_boundaries():
    material = "\n\n".join("[a.md, p. %d]\n%s" % (i, "x" * 90) for i in range(10))
    pieces = budget.pieces(material, 300)
    assert len(pieces) > 1
    assert all(len(p) <= 300 for p in pieces)
    assert "".join(p.replace("\n\n", "") for p in pieces).count("[a.md") == 10
