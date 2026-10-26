"""Recursive character text splitter.

Splits text into chunks of at most ``chunk_size`` characters. Boundaries are
chosen recursively: paragraphs first, then lines, then words, and a word is
cut only when it alone is too long.

Paragraph breaks are hard boundaries: a chunk may hold several whole
paragraphs, but part of a paragraph is never joined with another paragraph.
Inside a paragraph, a chunk ends early at a line or word boundary only when
that keeps the next piece whole; otherwise it is filled up, so long lines
(such as PDF layout lines) do not leave small fragments behind.

Each chunk after the first also begins with up to ``overlap_size`` characters
of the text that precedes it, starting at a word boundary when the overlap
window contains one, so context carries across chunk borders. Every chunk is
an exact (whitespace-trimmed) slice of the input text.
"""

from collections.abc import Collection, Iterator, Sequence

DEFAULT_SEPARATORS = ("\n\n", "\n", " ", "")
DEFAULT_HARD_SEPARATORS = ("\n\n",)

Span = tuple[int, int]


class RecursiveTextSplitter:

    def __init__(self, chunk_size: int, overlap_size: int = 0,
                 separators: Sequence[str] = DEFAULT_SEPARATORS,
                 hard_separators: Collection[str] = DEFAULT_HARD_SEPARATORS):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if not 0 <= overlap_size < chunk_size:
            raise ValueError("overlap_size must be >= 0 and smaller than chunk_size")
        if not separators or separators[-1] != "":
            raise ValueError("separators must end with '' so any text can be split")

        self.chunk_size = chunk_size
        self.overlap_size = overlap_size
        self.separators = tuple(separators)
        self.hard_separators = frozenset(hard_separators)
        # Room left for each chunk's own text once the overlap is prepended.
        self._body_size = chunk_size - overlap_size

    def split(self, text: str) -> list[str]:
        chunks = []
        for index, (start, end) in enumerate(self._split_spans(text, 0, len(text), self.separators)):
            if index:
                start = self._overlap_start(text, start)
            chunks.append(text[start:end].strip())
        return chunks

    def _split_spans(self, text: str, start: int, end: int,
                     separators: tuple[str, ...]) -> list[Span]:
        """Split text[start:end] into spans of at most _body_size characters."""
        separator, finer_separators = self._pick_separator(text, start, end, separators)
        if not separator:
            # No boundary left to respect: cut at fixed widths.
            fixed = ((position, min(position + self._body_size, end))
                     for position in range(start, end, self._body_size))
            return [(s, e) for s, e in fixed if not text[s:e].isspace()]

        spans: list[Span] = []
        group: Span | None = None
        for piece_start, piece_end in self._pieces(text, start, end, separator):
            if text[piece_start:piece_end].isspace() or piece_start == piece_end:
                continue

            if piece_end - piece_start > self._body_size and separator in self.hard_separators:
                # Never join part of this piece (e.g. a paragraph) with
                # anything across a hard boundary: close the open group and
                # split the piece on its own.
                if group:
                    spans.append(group)
                    group = None
                spans.extend(self._split_spans(text, piece_start, piece_end, finer_separators))
                continue

            if piece_end - piece_start > self._body_size:
                # The piece has to be split anyway, so ending the current chunk
                # early would keep nothing whole: split it together with the
                # open group, filling that chunk up, and keep the remainder
                # open so it can merge with the pieces that follow.
                region_start = group[0] if group else piece_start
                sub_spans = self._split_spans(text, region_start, piece_end, finer_separators)
                spans.extend(sub_spans[:-1])
                group = sub_spans[-1]
                continue

            if group and piece_end - group[0] > self._body_size:
                spans.append(group)
                group = None
            group = (group[0] if group else piece_start, piece_end)

        if group:
            spans.append(group)
        return spans

    @staticmethod
    def _pick_separator(text: str, start: int, end: int,
                        separators: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
        """Return the coarsest separator present in the span and the finer ones."""
        for index, separator in enumerate(separators):
            if separator == "" or text.find(separator, start, end) != -1:
                return separator, separators[index + 1:]
        return "", ()

    @staticmethod
    def _pieces(text: str, start: int, end: int, separator: str) -> Iterator[Span]:
        position = start
        while (found := text.find(separator, position, end)) != -1:
            yield position, found
            position = found + len(separator)
        yield position, end

    def _overlap_start(self, text: str, start: int) -> int:
        """Move a chunk start back by up to overlap_size, to a word boundary."""
        if not self.overlap_size:
            return start

        window_start = max(0, start - self.overlap_size)
        if window_start == 0 or text[window_start - 1].isspace():
            return window_start

        # The window begins mid-word: skip to the next whitespace so no word
        # is cut. Without any whitespace (one very long word) cut exactly.
        for position in range(window_start, start):
            if text[position].isspace():
                return position
        return window_start
