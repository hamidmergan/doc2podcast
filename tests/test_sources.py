import pytest

from conftest import make_docx, make_pdf, make_pptx
from doc2podcast import sources
from doc2podcast.errors import EmptyTextError, UnsupportedFileError


def test_reads_markdown_without_its_markup(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("# Title\n\nSome **bold** text and a [link](http://x).\n", encoding="utf-8")
    source = sources.read_file(path)
    assert "Title" in source.text
    assert "**" not in source.text
    assert "link" in source.text and "http://x" not in source.text


def test_reads_plain_text(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("One line.\nAnother line.\n", encoding="utf-8")
    assert sources.read_file(path).text == "One line.\nAnother line."


def test_reads_a_pdf_page_by_page(tmp_path):
    make_pdf(tmp_path / "a.pdf", ["First line", "Second line"])
    source = sources.read_file(tmp_path / "a.pdf")
    assert source.pages == 1
    assert "First line" in source.text


def test_reads_a_docx(tmp_path):
    make_docx(tmp_path / "a.docx", ["Hello there", "Second paragraph"])
    assert "Second paragraph" in sources.read_file(tmp_path / "a.docx").text


def test_every_slide_of_a_pptx_is_a_page(tmp_path):
    make_pptx(tmp_path / "a.pptx", ["Slide one", "Slide two"])
    source = sources.read_file(tmp_path / "a.pptx")
    assert source.pages == 2
    assert "Slide two" in source.text


def test_a_subtitle_file_loses_its_timings(tmp_path):
    path = tmp_path / "a.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello there\n\n"
                    "2\n00:00:02,000 --> 00:00:03,000\nSecond line\n", encoding="utf-8")
    text = sources.read_file(path).text
    assert text == "Hello there\nSecond line"


def test_an_unknown_type_names_what_is_allowed(tmp_path):
    path = tmp_path / "a.odt"
    path.write_bytes(b"x")
    with pytest.raises(UnsupportedFileError) as info:
        sources.read_file(path)
    assert ".pdf" in str(info.value)


def test_a_file_without_text_is_refused(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("   \n\n", encoding="utf-8")
    with pytest.raises(EmptyTextError):
        sources.read_file(path)


def test_a_missing_file_says_so(tmp_path):
    with pytest.raises(UnsupportedFileError) as info:
        sources.read_file(tmp_path / "gone.txt")
    assert "not found" in str(info.value)


def test_material_names_file_and_page(tmp_path):
    (tmp_path / "a.txt").write_text("Alpha text.", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Beta text.", encoding="utf-8")
    text = sources.material(sources.read_all([tmp_path / "a.txt", tmp_path / "b.txt"]))
    assert "[a.txt, p. 1]" in text
    assert "[b.txt, p. 1]" in text
    assert "Alpha text." in text and "Beta text." in text


def test_material_keeps_the_budget(tmp_path):
    (tmp_path / "a.txt").write_text("Q" * 500, encoding="utf-8")
    (tmp_path / "b.txt").write_text("Z" * 500, encoding="utf-8")
    read = sources.read_all([tmp_path / "a.txt", tmp_path / "b.txt"])
    text = sources.material(read, max_chars=200)
    assert text.count("Q") == 100 and text.count("Z") == 100


def test_material_without_a_source_is_refused():
    with pytest.raises(EmptyTextError):
        sources.material([])


def test_standalone_accents_are_put_back_on_their_letter():
    assert sources.clean("naïve") == "naïve"
    assert "\x00" not in sources.clean("a\x00b")


def test_read_bytes_takes_the_type_from_the_name():
    assert sources.read_bytes("a.txt", b"Hello").text == "Hello"
