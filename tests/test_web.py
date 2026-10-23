import time

import pytest
from fastapi.testclient import TestClient

from conftest import needs_ffmpeg
from doc2podcast import config
from doc2podcast.web.app import create_app


@pytest.fixture
def client(server, conf):
    settings = config.resolve(**conf)
    with TestClient(create_app(settings)) as made:
        yield made


@pytest.fixture
def bare():
    with TestClient(create_app(None)) as made:
        yield made


def wait(client, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get("/api/job").json()
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def upload(text="The deposit belongs to the tenant. Only real damage may be kept."):
    return [("files", ("paper.md", text.encode("utf-8"), "text/markdown"))]


def test_the_page_is_served(client):
    answer = client.get("/")
    assert answer.status_code == 200
    assert "Podcast" in answer.text
    assert "Continue to the cast" in answer.text


def test_the_page_offers_the_same_fields_as_the_tool(client):
    page = client.get("/").text
    for label in ("Podcast language", "Instruction, optional", "Who speaks?",
                  "Number of people", "Length", "Style", "The script is being written",
                  "Voicing", "Your podcast is ready", "Download MP3",
                  "Download transcript"):
        assert label in page


def test_info_names_the_choices(client):
    info = client.get("/api/info").json()
    assert info["languages"] == ["de", "en"]
    assert info["styles"] == ["teaching", "casual", "interview"]
    assert info["lengths"] == {"short": 5.0, "medium": 10.0, "long": 20.0}
    assert info["role_names"] == ["host", "expert", "student", "critic"]
    assert info["max_persons"] == 4
    assert ".pptx" in info["extensions"]
    assert info["model"] == "chat-model"


def test_info_works_without_settings(bare):
    info = bare.get("/api/info").json()
    assert info["base_url"] == ""
    assert info["speakers"] == 2
    assert info["has_key"] is False


def test_a_script_is_written_and_returned(client, server):
    answer = client.post("/api/script", files=upload(),
                         data={"minutes": "5", "language": "en", "speakers": "2"})
    assert answer.status_code == 200
    job = wait(client)
    assert job["state"] == "done" and job["step"] == "script"
    assert len(job["lines"]) == 27
    assert [p["name"] for p in job["persons"]] == ["Ana", "Ben"]


def test_the_names_and_roles_of_the_page_reach_the_prompt(client, server):
    client.post("/api/script", files=upload(),
                data={"minutes": "5", "names": "Mia,Noah", "roles": "host,critic"})
    wait(client)
    user = server.chat_requests[-1]["body"]["messages"][1]["content"]
    assert "0: Mia (host" in user and "1: Noah (critical voice" in user


def test_a_run_without_a_file_is_refused(client):
    assert client.post("/api/script", data={"minutes": "5"}).status_code == 400


def test_a_file_without_text_is_refused(client):
    answer = client.post(
        "/api/script",
        files=[("files", ("empty.txt", b"   ", "text/plain"))],
        data={"minutes": "5"},
    )
    assert answer.status_code == 400
    assert "No text" in answer.json()["detail"]


def test_several_files_become_one_episode(client, server):
    files = [("files", ("a%d.txt" % i, b"Some material about the matter.", "text/plain"))
             for i in range(3)]
    assert client.post("/api/script", files=files, data={"minutes": "5"}).status_code == 200
    wait(client)
    system = server.chat_requests[0]["body"]["messages"][0]["content"]
    assert "a0.txt, a1.txt, a2.txt" in system


def test_too_many_files_are_refused(client, monkeypatch):
    monkeypatch.setenv("DOC2PODCAST_MAX_SOURCES", "2")
    files = [("files", ("a%d.txt" % i, b"Some material.", "text/plain")) for i in range(3)]
    answer = client.post("/api/script", files=files, data={"minutes": "5"})
    assert answer.status_code == 400
    assert "too many files" in answer.json()["detail"]


def test_a_missing_chat_setting_is_reported(bare):
    answer = bare.post("/api/script", files=upload(), data={"minutes": "5"})
    assert answer.status_code == 400
    assert "DOC2PODCAST_BASE_URL" in answer.json()["detail"]


def test_a_broken_server_ends_the_job(client, server):
    server.fail = True
    client.post("/api/script", files=upload(), data={"minutes": "5"})
    job = wait(client)
    assert job["state"] == "error" and job["error"]


def test_only_one_job_at_a_time(client, server):
    client.post("/api/script", files=upload(), data={"minutes": "20"})
    second = client.post("/api/script", files=upload(), data={"minutes": "5"})
    assert second.status_code == 409
    wait(client)


@needs_ffmpeg
def test_a_reviewed_script_is_voiced(client, server):
    payload = {
        "lines": [{"speaker": 0, "text": "Hello and welcome."},
                  {"speaker": 1, "text": "Good to be here."}],
        "persons": [{"name": "Ana", "role": "host", "voice": "alloy"},
                    {"name": "Ben", "role": "expert", "voice": "echo"}],
        "language": "en",
        "speed": 1.0,
    }
    assert client.post("/api/render", json=payload).status_code == 200
    job = wait(client)
    assert job["state"] == "done" and job["has_audio"]
    spoken = {r["body"]["input"]: r["body"]["voice"] for r in server.speech_requests}
    assert spoken == {"Hello and welcome.": "alloy", "Good to be here.": "echo"}

    audio = client.get("/api/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/mpeg"
    assert audio.content

    text = client.get("/api/transcript")
    assert "Ana: Hello and welcome." in text.text

    script = client.get("/api/script.md")
    assert "**Ben:** Good to be here." in script.text


def test_voicing_without_a_voice_is_refused(client):
    payload = {
        "lines": [{"speaker": 0, "text": "Hello."}, {"speaker": 1, "text": "Hi."}],
        "persons": [{"name": "Ana", "role": "host", "voice": ""},
                    {"name": "Ben", "role": "expert", "voice": ""}],
    }
    answer = client.post("/api/render", json=payload)
    assert answer.status_code == 400
    assert "voices" in answer.json()["detail"]


def test_voicing_without_a_contribution_is_refused(client):
    assert client.post("/api/render", json={"lines": [], "persons": []}).status_code == 400


def test_a_contribution_of_an_unknown_person_is_refused(client):
    payload = {
        "lines": [{"speaker": 3, "text": "Hello."}],
        "persons": [{"name": "Ana", "role": "host", "voice": "alloy"}],
    }
    assert client.post("/api/render", json=payload).status_code == 400


def test_there_is_no_audio_before_a_run(client):
    assert client.get("/api/audio").status_code == 404
    assert client.get("/api/transcript").status_code == 404


def test_an_unknown_host_is_refused(server, conf):
    settings = config.resolve(**conf)
    app = create_app(settings, allowed_hosts=["127.0.0.1"])
    with TestClient(app, base_url="http://elsewhere") as made:
        assert made.get("/api/info").status_code == 400


def test_a_foreign_origin_is_refused(client):
    answer = client.get("/api/info", headers={"Origin": "http://evil.example"})
    assert answer.status_code == 403


def test_the_own_origin_is_allowed(client):
    answer = client.get("/api/info", headers={"Origin": "http://testserver"})
    assert answer.status_code == 200
