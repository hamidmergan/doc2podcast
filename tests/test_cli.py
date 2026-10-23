import pytest

from conftest import needs_ffmpeg
from doc2podcast import markdown
from doc2podcast.cli import main


def flags(conf):
    return [
        "--base-url", conf["base_url"],
        "--model", conf["model"],
        "--tts-model", conf["tts_model"],
        "--voices", conf["voices"],
        "--concurrency", "1",
        "--quiet",
    ]


def test_help_is_english(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "Turn documents into a podcast conversation" in out
    assert "--script-only" in out and "--from-script" in out


def test_the_version_is_printed(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "doc2podcast" in capsys.readouterr().out


def test_without_a_file_the_cli_says_what_to_do(capsys):
    assert main([]) == 2
    assert "at least one document" in capsys.readouterr().err


def test_files_and_from_script_do_not_go_together(capsys, tmp_path):
    assert main(["a.pdf", "--from-script", "s.md"]) == 2
    assert "not both" in capsys.readouterr().err


def test_script_only_writes_markdown(server, conf, material, tmp_path, capsys):
    target = tmp_path / "paper.md"
    assert main([str(material), "--script-only", "-o", str(target),
                 "--minutes", "5"] + flags(conf)) == 0
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# Podcast script")
    assert len(markdown.from_markdown(text)[0]) == 27


def test_script_only_defaults_to_the_name_of_the_first_file(server, conf, material):
    assert main([str(material), "--script-only", "--minutes", "5"] + flags(conf)) == 0
    assert (material.parent / "paper (1).md").exists()


def test_a_script_goes_to_stdout(server, conf, material, capsys):
    assert main([str(material), "--script-only", "-o", "-", "--minutes", "5"]
                + flags(conf)) == 0
    assert "# Podcast script" in capsys.readouterr().out


@needs_ffmpeg
def test_a_full_run_writes_an_mp3(server, conf, material, tmp_path):
    target = tmp_path / "out.mp3"
    assert main([str(material), "-o", str(target), "--minutes", "5"] + flags(conf)) == 0
    assert target.stat().st_size > 0
    assert len(server.speech_requests) == 27


@needs_ffmpeg
def test_from_script_voices_a_reviewed_script(server, conf, tmp_path):
    script = tmp_path / "s.md"
    script.write_text("Ana: Hello there.\n\nBen: Good to be here.\n", encoding="utf-8")
    assert main(["--from-script", str(script), "-o", str(tmp_path / "s.mp3")]
                + flags(conf)) == 0
    assert [r["body"]["voice"] for r in server.speech_requests] == ["alloy", "echo"]


def test_a_missing_setting_ends_with_code_two(material, capsys):
    assert main([str(material), "--script-only", "-o", "-"]) == 2
    assert "DOC2PODCAST_BASE_URL" in capsys.readouterr().err


def test_a_broken_server_ends_with_code_one(server, conf, material, capsys):
    server.fail = True
    assert main([str(material), "--script-only", "-o", "-", "--minutes", "5"]
                + flags(conf)) == 1
    assert "Error:" in capsys.readouterr().err


def test_an_unknown_file_type_ends_with_code_one(server, conf, tmp_path, capsys):
    path = tmp_path / "a.odt"
    path.write_bytes(b"x")
    assert main([str(path), "--script-only", "-o", "-"] + flags(conf)) == 1
    assert "not supported" in capsys.readouterr().err


def test_an_impossible_setting_ends_with_code_two(server, conf, material, capsys):
    assert main([str(material), "--script-only", "-o", "-", "--speakers", "9"]
                + flags(conf)) == 2
    assert "speakers must be between" in capsys.readouterr().err


def test_serve_without_the_extra_packages_says_how_to_install(monkeypatch, capsys):
    import builtins

    real = builtins.__import__

    def no_uvicorn(name, *args, **kwargs):
        if name == "uvicorn":
            raise ImportError("no uvicorn")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_uvicorn)
    assert main(["serve"]) == 2
    assert "doc2podcast[ui]" in capsys.readouterr().err
