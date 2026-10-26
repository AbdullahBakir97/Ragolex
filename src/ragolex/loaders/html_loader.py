import re
from html.parser import HTMLParser
from pathlib import Path

from ragolex.domain.models import Document

from .sections import Block, Heading, documents_by_section

# Elements whose content is not text a reader sees, or is page furniture.
_SKIPPED = {"script", "style", "noscript", "template", "svg", "math", "iframe", "object",
            "canvas", "head", "nav", "footer", "form", "button", "select"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "source", "track", "wbr"}
# Elements that end a line of text.
_BLOCKS = {"address", "article", "aside", "blockquote", "dd", "details", "div", "dl", "dt",
           "figcaption", "figure", "header", "hr", "li", "main", "ol", "p", "pre", "section",
           "summary", "table", "tr", "ul", "br", "caption"}
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_SPACES = re.compile(r"\s+")


class HtmlLoader:
    """Loads an HTML page's readable text as one document per section.

    Scripts, styles, navigation, footers and forms are left out; headings
    start sections, and the page's ``<title>`` is kept as ``title`` metadata.
    """

    def load(self, path: Path, source: str) -> list[Document]:
        text = path.read_text(encoding="utf-8", errors="replace")
        title, blocks = parse(text)
        return documents_by_section(blocks, source, {"title": title} if title else None)


def parse(html: str) -> tuple[str | None, list[Block]]:
    """The page's title, and its text as headings and paragraphs."""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    parser.end_line()
    return parser.title, parser.blocks


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.title: str | None = None
        self._open: list[tuple[str, bool]] = []
        self._skipping = 0
        self._line: list[str] = []
        self._heading: int | None = None
        self._pre = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            if tag in _BLOCKS and not self._skipping:
                self.end_line()
            return
        if tag == "body":
            self.handle_endtag("head")  # Often left open.
        skips = tag in _SKIPPED or any(name == "hidden" for name, _ in attrs)
        self._open.append((tag, skips))
        if tag == "title":
            self._in_title = True
        if skips:
            self._skipping += 1
        if self._skipping:
            return
        if tag in _HEADINGS:
            self.end_line()
            self._heading = _HEADINGS[tag]
        elif tag in _BLOCKS:
            self.end_line()
            if tag == "li":
                self._line.append("- ")
            elif tag == "pre":
                self._pre += 1
        elif tag in ("td", "th") and self._line:
            self._line.append(" | ")

    def handle_endtag(self, tag):
        if not any(opened == tag for opened, _ in self._open):
            return  # A stray end tag.
        # Close everything opened inside it too, as browsers do.
        while self._open:
            opened, skips = self._open.pop()
            self._close(opened, skips)
            if opened == tag:
                break

    def _close(self, tag, skips):
        if tag == "title":
            self._in_title = False
        if self._skipping:
            self._skipping -= skips
            return
        if tag in _HEADINGS:
            text = self._text()
            self._line.clear()
            if text:
                self.blocks.append(Heading(_HEADINGS[tag], text))
            self._heading = None
        elif tag in _BLOCKS:
            self.end_line()
            if tag == "pre":
                self._pre -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title = _SPACES.sub(" ", (self.title or "") + data).strip() or None
        elif not self._skipping:
            self._line.append(data if self._pre else _SPACES.sub(" ", data))

    def end_line(self):
        if self._heading is not None:
            return  # Block elements inside a heading don't split it.
        text = self._text()
        self._line.clear()
        if text:
            self.blocks.append(text)

    def _text(self) -> str:
        text = "".join(self._line)
        return text.strip("\n") if self._pre else _SPACES.sub(" ", text).strip()
