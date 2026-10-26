from dataclasses import dataclass

from ragolex.domain.models import Document


@dataclass(frozen=True)
class Heading:
    level: int
    text: str


Block = Heading | str


def documents_by_section(blocks: list[Block], source: str,
                         metadata: dict | None = None) -> list[Document]:
    """One document per section, so chunks never mix two sections.

    Each section starts with its heading, and its ``section`` metadata is the
    path of headings above it (``"Setup > Install"``). Text before the first
    heading is a section without one; a heading with no text of its own,
    such as a title right before its first subheading, makes no document.
    """
    documents: list[Document] = []
    path: list[Heading] = []
    body: list[str] = []

    def close():
        if body:
            heading = [f"{'#' * path[-1].level} {path[-1].text}"] if path else []
            section = {"section": " > ".join(h.text for h in path)} if path else {}
            documents.append(Document(text="\n\n".join(heading + body), metadata={
                "source": source, **(metadata or {}), **section}))
        body.clear()

    for block in blocks:
        if isinstance(block, Heading):
            close()
            path[:] = [h for h in path if h.level < block.level] + [block]
        elif block.strip():
            body.append(_trim(block))
    close()
    return documents


def _trim(block: str) -> str:
    """The block without blank lines around it, keeping its first line's indent."""
    lines = block.rstrip().splitlines()
    while not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines)
