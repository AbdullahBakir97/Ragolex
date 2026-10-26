import re
from pathlib import Path

from ragolex.domain.models import Document

from .sections import Block, Heading, documents_by_section

_ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])[ \t]")


class MarkdownLoader:
    """Loads a Markdown file as one document per section.

    The text keeps its Markdown, which models read well; headings (``#``
    lines and underlined ones) start sections, except inside code blocks.
    A YAML front matter block at the top is left out.
    """

    def load(self, path: Path, source: str) -> list[Document]:
        text = path.read_text(encoding="utf-8", errors="replace")
        return documents_by_section(parse(text), source)


def parse(text: str) -> list[Block]:
    lines = _without_front_matter(text.splitlines())
    blocks: list[Block] = []
    run: list[str] = []
    fence: str | None = None

    def flush():
        if run:
            blocks.append("\n".join(run))
            run.clear()

    for line in lines:
        if fence is not None:
            run.append(line)
            if line.strip().startswith(fence):
                fence = None
            continue
        if match := _FENCE.match(line):
            fence = match.group(1)
            run.append(line)
            continue
        if match := _ATX.match(line):
            flush()
            blocks.append(Heading(len(match.group(1)), match.group(2).strip()))
            continue
        # An underlined heading: one line of text, then === or ---.
        setext = _SETEXT.match(line)
        if (setext and run and run[-1].strip() and not _LIST_ITEM.match(run[-1])
                and (len(run) == 1 or not run[-2].strip())):
            title = run.pop().strip()
            flush()
            blocks.append(Heading(1 if setext.group(1)[0] == "=" else 2, title))
            continue
        run.append(line)
    flush()
    return blocks


def _without_front_matter(lines: list[str]) -> list[str]:
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() in ("---", "..."):
                return lines[index + 1:]
    return lines
