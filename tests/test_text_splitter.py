import random

import pytest

from ragolex.text.splitter import RecursiveTextSplitter

PARAGRAPHS = (
    "Retrieval-augmented generation combines search with a language model.\n\n"
    "First, documents are split into chunks and indexed.\n"
    "Then, the most relevant chunks are retrieved for each question.\n\n"
    "Finally, the model answers using the retrieved context."
)


def split(text, chunk_size, overlap_size=0):
    return RecursiveTextSplitter(chunk_size, overlap_size).split(text)


def shared_words(previous: str, following: str) -> list[str]:
    """Longest run of words that ends `previous` and starts `following`."""
    prev, foll = previous.split(), following.split()
    for size in range(min(len(prev), len(foll)), 0, -1):
        if prev[-size:] == foll[:size]:
            return prev[-size:]
    return []


def test_short_text_is_one_chunk():
    assert split("Hello world.", chunk_size=100) == ["Hello world."]


@pytest.mark.parametrize("text", ["", "   ", "\n\n\n"])
def test_blank_text_gives_no_chunks(text):
    assert split(text, chunk_size=100) == []


@pytest.mark.parametrize(("chunk_size", "overlap_size"), [(20, 5), (50, 10), (80, 30), (200, 50)])
def test_chunks_never_exceed_chunk_size(chunk_size, overlap_size):
    chunks = split(PARAGRAPHS, chunk_size, overlap_size)

    assert chunks
    assert all(len(chunk) <= chunk_size for chunk in chunks)


@pytest.mark.parametrize(("chunk_size", "overlap_size"), [(20, 0), (50, 10), (80, 30)])
def test_chunks_are_exact_slices_of_the_text(chunk_size, overlap_size):
    chunks = split(PARAGRAPHS, chunk_size, overlap_size)

    assert all(chunk in PARAGRAPHS for chunk in chunks)


@pytest.mark.parametrize("chunk_size", [20, 50, 80])
def test_no_words_are_lost_without_overlap(chunk_size):
    chunks = split(PARAGRAPHS, chunk_size)

    assert " ".join(chunks).split() == PARAGRAPHS.split()


def test_prefers_paragraph_boundaries():
    text = "a" * 30 + "\n\n" + "b" * 30

    assert split(text, chunk_size=40) == ["a" * 30, "b" * 30]


def test_pieces_that_fit_are_kept_whole():
    text = "\n\n".join(letter * 30 for letter in "abc")

    assert split(text, chunk_size=40) == ["a" * 30, "b" * 30, "c" * 30]


def test_long_lines_do_not_leave_fragments():
    # Each line is longer than a chunk, so splitting lines one by one would
    # leave a short leftover per line. Chunks must be filled up instead.
    line = "one printed line of a PDF page that is wrapped by the layout engine"
    text = "\n".join([line] * 10)
    longest_word = max(len(word) for word in text.split())

    chunks = split(text, chunk_size=50)

    assert all(len(chunk) > 50 - longest_word - 1 for chunk in chunks[:-1])


def test_short_line_before_a_long_one_is_filled_up():
    text = "Intro.\n" + " ".join(["word"] * 30)

    first = split(text, chunk_size=40)[0]

    assert first.startswith("Intro.") and "word" in first


def test_part_of_a_paragraph_is_never_joined_with_another_paragraph():
    # Regression: with fill-up across paragraph breaks this produced
    # "Line one.\n\nLine" as the first chunk.
    text = "Line one.\n\nLine two of the notes."

    assert split(text, chunk_size=15) == ["Line one.", "Line two of the", "notes."]


def test_whole_paragraphs_still_share_a_chunk():
    text = "Short one.\n\nShort two.\n\n" + " ".join(["long"] * 20)

    assert split(text, chunk_size=30)[0] == "Short one.\n\nShort two."


def test_hard_separators_are_configurable():
    text = "Line one.\nLine two of the notes."

    assert split(text, chunk_size=15)[0] == "Line one.\nLine"
    assert RecursiveTextSplitter(15, hard_separators=("\n\n", "\n")).split(text)[0] == "Line one."


def test_overlap_carries_preceding_words():
    text = " ".join(f"w{i:02d}" for i in range(40))  # 3-character words

    chunks = split(text, chunk_size=30, overlap_size=10)

    for previous, following in zip(chunks, chunks[1:], strict=False):
        overlap = " ".join(shared_words(previous, following))
        assert 7 <= len(overlap) <= 10  # "w05 w06" or "w05 w06 w07"


def test_overlap_works_when_lines_are_longer_than_overlap():
    # PDF text arrives as many ~100-character lines; overlap must still apply.
    line = "This sentence is one printed line of a PDF page, wrapped by the layout engine."
    text = "\n".join(f"{line} ({i})" for i in range(8))

    chunks = split(text, chunk_size=300, overlap_size=40)

    assert len(chunks) > 1
    for previous, following in zip(chunks, chunks[1:], strict=False):
        assert shared_words(previous, following)


def test_overlap_never_starts_mid_word():
    text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
    words = set(text.split())

    for chunk in split(text, chunk_size=25, overlap_size=12):
        assert set(chunk.split()) <= words


def test_word_longer_than_chunk_size_is_cut():
    assert split("x" * 25, chunk_size=10) == ["x" * 10, "x" * 10, "x" * 5]


def test_long_word_overlap_is_cut_exactly():
    assert split("abcdefghijklmnopqrstuvwxy", chunk_size=10, overlap_size=3) == [
        "abcdefg", "efghijklmn", "lmnopqrstu", "stuvwxy",
    ]


def test_random_texts_respect_size_and_are_slices():
    rng = random.Random(1)
    words = ["a", "bb", "rag", "vector", "embedding", "x" * 40]
    for _ in range(2000):
        text = "".join(
            rng.choice(words) + rng.choice([" ", " ", "  ", "\n", "\n\n"])
            for _ in range(rng.randint(0, 60))
        )
        chunk_size = rng.randint(5, 120)
        overlap_size = rng.randint(0, chunk_size - 1)

        chunks = split(text, chunk_size, overlap_size)

        assert all(0 < len(chunk) <= chunk_size for chunk in chunks)
        assert all(chunk in text for chunk in chunks)
        if overlap_size == 0:
            assert "".join("".join(chunks).split()) == "".join(text.split())


def test_fixed_width_cut_never_yields_blank_chunks():
    # Regression: cutting a region that contains spaces at fixed widths
    # produced whitespace-only spans, which became empty chunks.
    text = "embedding  embedding\nrag\n\nvector\nrag bb rag " + "x" * 40 + "  bb vector\n\na\n"

    chunks = split(text, chunk_size=29, overlap_size=28)

    assert chunks and all(chunk.strip() for chunk in chunks)


@pytest.mark.parametrize(
    ("chunk_size", "overlap_size"),
    [(0, 0), (-5, 0), (10, 10), (10, 20), (10, -1)],
)
def test_invalid_sizes_raise(chunk_size, overlap_size):
    with pytest.raises(ValueError):
        RecursiveTextSplitter(chunk_size, overlap_size)


def test_separators_must_end_with_empty_string():
    with pytest.raises(ValueError):
        RecursiveTextSplitter(10, separators=("\n\n", " "))
