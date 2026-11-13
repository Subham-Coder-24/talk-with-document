from pathlib import Path

import pytest

from app.services.parsers import UnsupportedFile, parse_file


def test_text_file(tmp_path: Path):
    f = tmp_path / "notes.md"
    f.write_text("# Title\n\nSome notes", encoding="utf-8")
    assert parse_file(f)[0].text.startswith("# Title")


def test_csv_rows_become_records(tmp_path: Path):
    f = tmp_path / "people.csv"
    f.write_text("name,city\nAlice,London\n", encoding="utf-8")
    assert parse_file(f)[0].text == "name: Alice; city: London"


def test_unknown_text_extension_is_accepted(tmp_path: Path):
    f = tmp_path / "data.custom"
    f.write_text("plain text content", encoding="utf-8")
    assert parse_file(f)[0].text == "plain text content"


def test_binary_is_rejected(tmp_path: Path):
    f = tmp_path / "blob.bin"
    f.write_bytes(bytes(range(256)))
    with pytest.raises(UnsupportedFile):
        parse_file(f)


def test_docx_tables_and_headings(tmp_path: Path):
    import docx

    d = docx.Document()
    d.add_heading("Budget", 1)
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Build", "$480k"
    f = tmp_path / "b.docx"
    d.save(f)
    text = parse_file(f)[0].text
    assert "# Budget" in text and "Build | $480k" in text
