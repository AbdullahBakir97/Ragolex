"""Quoting text the prompts did not write, such as documents and questions.

Prompts put that text between tags of their own (``<source>`` and
``</source>``), and the system message says it is data. A tag inside the
text could end its section early and pose as instructions, so the ``<``
that opens one is escaped as ``&lt;`` by ``neutralize``. Tags are found the way a reader,
or a model, sees them rather than only as exact text: in any case, with
spaces (``< / source >``), with invisible characters inside
(``</so\\u200burce>``), and with characters that look like the brackets,
the slash or the letters: fullwidth forms (``＜/ｓｏｕｒｃｅ＞``) and Cyrillic
or Greek letters that look Latin (``</sоurce>`` with a Cyrillic о).
Nothing else in the text changes.
"""

import re
from collections.abc import Callable

# Characters that show nothing: the soft hyphen, zero-width spaces and joiners,
# direction marks and overrides, word joiners and the byte-order mark.
_INVISIBLE = "[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"
# "<" and the characters that look like it.
_OPENING = "[<\u02c2\u2039\u2329\u27e8\u3008\ufe64\uff1c]"
# "/" and the characters that look like it.
_SLASH = "[/\u2044\u2215\u29f8\uff0f]"
# Fullwidth forms are the ASCII characters this far up.
_FULLWIDTH = 0xFEE0
# Cyrillic and Greek letters that look like Latin ones.
_LOOKALIKES = {"a": "\u0430\u03b1", "c": "\u0441\u03f2", "e": "\u0435\u03b5", "i": "\u0456\u03b9",
               "n": "\u03b7", "o": "\u043e\u03bf", "p": "\u0440\u03c1", "r": "\u0433",
               "s": "\u0455", "u": "\u03c5", "x": "\u0445\u03c7", "y": "\u0443"}


def neutralizer(*tags: str) -> Callable[[str], str]:
    """A function that escapes every opening or closing ``tags`` tag in a text."""
    gap = rf"(?:\s|{_INVISIBLE})*"
    names = "|".join(_spelled(tag) for tag in sorted(tags, key=len, reverse=True))
    pattern = re.compile(rf"{_OPENING}(?={gap}(?:{_SLASH}{gap})?(?:{names})(?!\w))",
                         re.IGNORECASE)

    def neutralize(text: str) -> str:
        return pattern.sub("&lt;", text)

    return neutralize


def _spelled(tag: str) -> str:
    """The tag's name as a pattern: each letter or its look-alikes, invisible characters between."""
    letters = (f"[{letter}{chr(ord(letter) + _FULLWIDTH)}{_LOOKALIKES.get(letter, '')}]"
               for letter in tag)
    return f"{_INVISIBLE}*".join(letters)


# Every tag a prompt uses. Each prompt escapes them all, not only its own, so
# quoted text cannot even pose as another prompt's sections.
PROMPT_TAGS = ("answer", "conversation", "question", "reference", "source", "sources")
neutralize = neutralizer(*PROMPT_TAGS)
