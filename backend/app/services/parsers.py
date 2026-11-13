"""Extract text from uploaded files.

Every parser returns a list of `Section`s. A section is a unit of text with an
optional page/slide number, which is carried through to chunks so answers can
cite "report.pdf, p. 4".
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Section:
    text: str
    page: int | None = None


class UnsupportedFile(Exception):
    pass


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".ini", ".cfg", ".toml", ".yaml", ".yml",
    ".xml", ".sql", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".go", ".rs",
    ".c", ".h", ".cpp", ".hpp", ".rb", ".php", ".sh", ".ps1", ".css", ".scss", ".r",
    ".kt", ".swift", ".scala", ".tex", ".srt", ".vtt",
}  # fmt: skip
LEGACY_OFFICE = {".doc", ".ppt", ".xls"}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def parse_file(path: Path) -> list[Section]:
    """Synchronous (CPU/IO bound) – call from a worker thread. Images are handled elsewhere."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(path)
    if ext in {".docx", ".docm"}:
        return _parse_docx(path)
    if ext in {".pptx", ".pptm"}:
        return _parse_pptx(path)
    if ext in {".xlsx", ".xlsm"}:
        return _parse_xlsx(path)
    if ext in {".csv", ".tsv"}:
        return _parse_csv(path, delimiter="\t" if ext == ".tsv" else ",")
    if ext in {".html", ".htm"}:
        return _parse_html(path)
    if ext == ".json":
        return _parse_json(path)
    if ext in LEGACY_OFFICE:
        raise UnsupportedFile(
            f"Legacy Office format '{ext}' is not supported; please save it as {ext}x and re-upload."
        )
    if ext in TEXT_EXTS:
        return [Section(_read_text(path))]
    # Unknown extension: accept it if it looks like text.
    if _looks_like_text(path):
        return [Section(_read_text(path))]
    raise UnsupportedFile(f"Unsupported file type '{ext or 'unknown'}'.")


# --- helpers -----------------------------------------------------------------


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue  # only trust utf-16 with a BOM
            return text
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _looks_like_text(path: Path, probe: int = 8192) -> bool:
    with path.open("rb") as f:
        head = f.read(probe)
    if not head:
        return False
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:
        # A multi-byte char cut at the probe boundary is fine.
        return exc.start >= len(head) - 4


def _parse_pdf(path: Path) -> list[Section]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise UnsupportedFile("PDF is password protected.") from exc
    sections = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # a single broken page shouldn't fail the document
            log.warning("Failed to extract page %s of %s", i, path.name, exc_info=True)
            text = ""
        if text.strip():
            sections.append(Section(text, page=i))
    if not sections and len(reader.pages):
        raise UnsupportedFile(
            "No extractable text in PDF (it is probably scanned images; OCR is not enabled)."
        )
    return sections


def _parse_docx(path: Path) -> list[Section]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))
    parts: list[str] = []
    # Walk the body in order so tables stay next to the text that introduces them.
    for block in document.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(block, document)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower() if para.style is not None else ""
            if style.startswith("heading"):
                level = "".join(ch for ch in style if ch.isdigit()) or "1"
                text = "#" * min(int(level), 6) + " " + text
            parts.append(text)
        elif tag == "tbl":
            table = Table(block, document)
            rows = []
            for row in table.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                rows.append(" | ".join(cells))
            if rows:
                parts.append("\n".join(rows))
    return [Section("\n\n".join(parts))]


def _parse_pptx(path: Path) -> list[Section]:
    from pptx import Presentation

    prs = Presentation(str(path))
    sections = []
    for i, slide in enumerate(prs.slides, start=1):
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                t = shape.text_frame.text.strip()
                if t:
                    texts.append(t)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    texts.append(" | ".join(c.text.strip() for c in row.cells))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                texts.append(f"Speaker notes: {notes}")
        if texts:
            sections.append(Section(f"Slide {i}\n" + "\n".join(texts), page=i))
    return sections


def _rows_to_text(header: list[str] | None, rows: list[list[str]]) -> str:
    """Render rows as 'col: value' records so each chunk is self-describing."""
    lines = []
    for row in rows:
        if not any(cell.strip() for cell in row):
            continue
        if header:
            pairs = [f"{h}: {v}" for h, v in zip(header, row) if str(v).strip()]
            lines.append("; ".join(pairs))
        else:
            lines.append(" | ".join(row))
    return "\n".join(lines)


def _parse_xlsx(path: Path) -> list[Section]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    sections = []
    try:
        for sheet in wb.worksheets:
            rows = [
                ["" if v is None else str(v) for v in row]
                for row in sheet.iter_rows(values_only=True)
            ]
            rows = [r for r in rows if any(c.strip() for c in r)]
            if not rows:
                continue
            header, body = rows[0], rows[1:]
            text = _rows_to_text(header if body else None, body or rows)
            sections.append(Section(f"Sheet: {sheet.title}\n{text}"))
    finally:
        wb.close()
    return sections


def _parse_csv(path: Path, delimiter: str) -> list[Section]:
    text = _read_text(path)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        return []
    header, body = rows[0], rows[1:]
    return [Section(_rows_to_text(header if body else None, body or rows))]


def _parse_html(path: Path) -> list[Section]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_read_text(path), "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return [Section(soup.get_text("\n", strip=True))]


def _parse_json(path: Path) -> list[Section]:
    raw = _read_text(path)
    try:
        return [Section(json.dumps(json.loads(raw), indent=2, ensure_ascii=False))]
    except json.JSONDecodeError:
        return [Section(raw)]
