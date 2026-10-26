import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

from ragolex.domain.models import Document

from .sections import Block, Heading, documents_by_section

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HEADING_STYLE = re.compile(r"^heading (\d)$")
# Word files are zip archives; this caps what one may expand to.
MAX_XML_BYTES = 64 * 1024 * 1024


class DocxLoader:
    """Loads a Word document (``.docx``) as one document per section.

    Paragraphs in heading styles start sections; tables become one line
    per row, and list items start with ``-``. The older ``.doc`` format is
    not supported.
    """

    def load(self, path: Path, source: str) -> list[Document]:
        with zipfile.ZipFile(path) as archive:
            body = _read_xml(archive, "word/document.xml").find(f"{_W}body")
            styles = _heading_styles(archive)
        return documents_by_section(list(_blocks(body, styles)) if body is not None else [],
                                    source)


def _read_xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    if archive.getinfo(name).file_size > MAX_XML_BYTES:
        raise ValueError(f"{name} is larger than {MAX_XML_BYTES} bytes")
    data = archive.read(name)
    # Word never writes a DTD; one could only be there to expand entities.
    if b"<!DOCTYPE" in data[:4096].upper():
        raise ValueError(f"{name} has a DTD")
    return ElementTree.fromstring(data)


def _heading_styles(archive: zipfile.ZipFile) -> dict[str, int]:
    """Heading level by style id.

    Ids are translated in some languages (``berschrift1``), while built-in
    style names stay ``heading 1``, so the names decide.
    """
    if "word/styles.xml" not in archive.namelist():
        return {}
    levels = {}
    for style in _read_xml(archive, "word/styles.xml").iter(f"{_W}style"):
        style_id = style.get(f"{_W}styleId")
        named = style.find(f"{_W}name")
        name = (named.get(f"{_W}val") or "").lower() if named is not None else ""
        if style_id is None:
            continue
        if name == "title":
            levels[style_id] = 1
        elif match := _HEADING_STYLE.match(name):
            levels[style_id] = int(match.group(1))
    return levels


def _blocks(parent: ElementTree.Element, styles: dict[str, int]) -> Iterator[Block]:
    for element in parent:
        if element.tag == f"{_W}p":
            text = _text(element).strip()
            if not text:
                continue
            properties = element.find(f"{_W}pPr")
            style = properties.find(f"{_W}pStyle") if properties is not None else None
            level = styles.get(style.get(f"{_W}val", "")) if style is not None else None
            if level:
                yield Heading(level, text)
            elif properties is not None and properties.find(f"{_W}numPr") is not None:
                yield f"- {text}"
            else:
                yield text
        elif element.tag == f"{_W}tbl":
            for row in element.findall(f"{_W}tr"):
                cells = [" ".join(_text(p).strip() for p in cell.iter(f"{_W}p")).strip()
                         for cell in row.findall(f"{_W}tc")]
                if any(cells):
                    yield " | ".join(cells)
        elif element.tag == f"{_W}sdt":
            # A content control, such as a table of contents, holds paragraphs too.
            content = element.find(f"{_W}sdtContent")
            if content is not None:
                yield from _blocks(content, styles)


def _text(paragraph: ElementTree.Element) -> str:
    parts = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts)
