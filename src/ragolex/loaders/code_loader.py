"""Source code, one document per definition.

A chunk that holds the end of one function and the start of the next
answers questions about neither well. So a code file is split where its
definitions start: each top-level function, class or other type is a
document of its own, with the comments, decorators and annotations right
above it, and its name as the ``section``. The lines between definitions,
such as imports and constants, make documents without a section. A class
longer than ``WHOLE_CLASS_CHARACTERS`` is split the same way into its
members (``Parser.parse``), the lines before its first member staying
under the class's own name.

Python is read with its own parser. The other languages, all with C-like
syntax (C, C++, C#, Go, Java, JavaScript, Kotlin, PHP, Rust, Swift and
TypeScript), are read by following their brackets, which needs no grammar
for each language. A file neither can follow, such as one with a syntax
error, still loads: as one document, split like any text.
"""

import ast
import re
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ragolex.domain.models import Document

# A class this long is split into its members.
WHOLE_CLASS_CHARACTERS = 1500


@dataclass
class _Definition:
    start: int  # its first line, 0-based, with the comments and decorators above it
    end: int  # one past its last line
    name: str
    members: list["_Definition"] = field(default_factory=list)  # a class's own definitions


class CodeLoader:
    """Loads a source file as one document per definition; see the module docstring."""

    def __init__(self, language: str):
        self.language = language

    def load(self, path: Path, source: str) -> list[Document]:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        definitions = (_python_definitions(lines) if self.language == "python"
                       else _bracket_definitions(lines, self.language))
        metadata = {"source": source, "language": self.language}
        if definitions is None:
            return [Document(text=text, metadata=metadata)] if text.strip() else []
        return [Document(text=text, metadata={**metadata, **({"section": name} if name else {})})
                for text, name in _pieces(lines, definitions)]


def _pieces(lines: list[str], definitions: list[_Definition]) -> list[tuple[str, str | None]]:
    """The file's text, cut where definitions start: (text, name) pairs, in order.

    Every line is in one piece, except blank ones and closing brackets left
    on their own (``}  // namespace geo``). Neighbouring lines that are no
    definition, such as the lines before a class's first member, are one
    piece.
    """
    spans: list[list] = []  # [start, end, name, is_definition]

    def add(start: int, end: int, name: str | None, is_definition: bool) -> None:
        if not any(_has_content(line) for line in lines[start:end]):
            return
        if spans and not is_definition and not spans[-1][3] and spans[-1][2] == name:
            spans[-1][1] = end
        else:
            spans.append([start, end, name, is_definition])

    def walk(definitions: list[_Definition], start: int, end: int, outer: str | None) -> None:
        position = start
        for definition in definitions:
            add(position, definition.start, outer, False)
            name = f"{outer}.{definition.name}" if outer else definition.name
            size = sum(len(line) + 1 for line in lines[definition.start:definition.end])
            if definition.members and size > WHOLE_CLASS_CHARACTERS:
                walk(definition.members, definition.start, definition.end, name)
            else:
                add(definition.start, definition.end, name, True)
            position = definition.end
        add(position, end, outer, False)

    walk(definitions, 0, len(lines), None)
    return [(textwrap.dedent("\n".join(lines[start:end])).strip("\n").rstrip(), name)
            for start, end, name, _ in spans]


def _has_content(line: str) -> bool:
    stripped = line.strip()
    return not stripped.startswith(tuple(_CLOSING)) and any(c.isalnum() for c in stripped)


def _attach(lines: list[str], first: int, floor: int, attached: Callable[[int], bool]) -> int:
    """Where a definition starts once the comments right above it (no blank line between) join it."""
    start = first
    while start > floor and lines[start - 1].strip() and attached(start - 1):
        start -= 1
    return start


# Python, with its own parser.

def _python_definitions(lines: list[str]) -> list[_Definition] | None:
    try:
        tree = ast.parse("\n".join(lines))
    except (SyntaxError, ValueError):
        return None
    return _python_body(tree.body, lines)


def _python_body(body: list[ast.stmt], lines: list[str]) -> list[_Definition]:
    definitions = []
    previous_end = body[0].lineno - 1 if body else 0
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = min([node.lineno, *(d.lineno for d in node.decorator_list)]) - 1
            start = _attach(lines, first, previous_end,
                            lambda index: lines[index].lstrip().startswith("#"))
            members = _python_body(node.body, lines) if isinstance(node, ast.ClassDef) else []
            definitions.append(_Definition(start, _end(node), node.name, members))
        previous_end = _end(node)
    return definitions


def _end(node: ast.stmt) -> int:
    return node.end_lineno if node.end_lineno is not None else node.lineno


# Languages with C-like syntax, by following their brackets.

_OPENING, _CLOSING = "([{", ")]}"


@dataclass
class _Lines:
    """Each line's bracket depth where it starts and ends, and whether it holds code.

    Brackets in comments, strings and character literals are not counted.
    Where single quotes are for characters, a quote that is not one, such
    as a Rust lifetime, is no literal.
    """
    starts: list[int]
    ends: list[int]
    code: list[bool]


# Languages whose single quotes are strings, not characters.
_SINGLE_QUOTE_STRINGS = {"javascript", "typescript", "php"}
_CHARACTER = re.compile(r"'(?:\\[^']{1,10}|[^'\\])'")


def _scan(lines: list[str], language: str) -> _Lines | None:
    """Follows the brackets; None when they do not balance, so the scan went wrong."""
    scanned = _Lines([], [], [])
    depth = 0
    open_until: str | None = None  # what ends the comment or string the line starts in
    for line in lines:
        scanned.starts.append(depth)
        has_code = False
        position = 0
        while position < len(line):
            if open_until is not None:
                close = line.find(open_until, position)
                if close < 0:
                    if open_until != "*/":
                        has_code = True
                    break
                position = close + len(open_until)
                has_code = has_code or open_until != "*/"
                open_until = None
                continue
            character = line[position]
            if line.startswith("//", position):
                break
            if line.startswith("/*", position):
                open_until, position = "*/", position + 2
                continue
            if character.isspace():
                position += 1
                continue
            has_code = True
            if line.startswith('"""', position):
                open_until, position = '"""', position + 3
                continue
            if character == "`":
                open_until, position = "`", position + 1
                continue
            if character == '"' or (character == "'" and language in _SINGLE_QUOTE_STRINGS):
                if (quote := _closing_quote(line, position)) is not None:
                    position = quote + 1
                    continue
            elif character == "'" and (literal := _CHARACTER.match(line, position)):
                position = literal.end()
                continue
            if character in _OPENING:
                depth += 1
            elif character in _CLOSING:
                depth -= 1
                if depth < 0:
                    return None
            position += 1
        scanned.ends.append(depth)
        scanned.code.append(has_code)
    return scanned if depth == 0 and open_until in (None, "*/") else None


def _closing_quote(line: str, opening: int) -> int | None:
    position = opening + 1
    while position < len(line):
        if line[position] == "\\":
            position += 2
            continue
        if line[position] == line[opening]:
            return position
        position += 1
    return None


_MODIFIERS = (r"(?:(?:export|default|public|private|protected|internal|fileprivate|static|"
              r"abstract|final|sealed|open|data|inner|partial|declare|unsafe|async|override|"
              r"virtual|extern(?:\s+\"\w+\")?|inline|const|readonly|suspend|mutating|"
              r"nonmutating|operator|infix|tailrec|external|actual|expect|convenience|required|"
              r"dynamic|nonisolated|value|annotation|enum|case|ref|pub(?:\s*\([\w\s]+\))?)\s+)*")
_FUNCTION = re.compile(
    r"^\s*" + _MODIFIERS + r"(?:class\s+)?(?:func|fn|fun|function\s*\*?)\s+"
    # A Go method's receiver: func (s *Server) Start() is Server.Start.
    r"(?:\(\s*\w*\s*\*?\s*([\w.]+)[^)]*\)\s*)?"
    r"(?:<[^>]*>\s*)?(?:[\w.]+\.)?([A-Za-z_$][\w$]*)")
_TYPE = re.compile(
    r"^\s*" + _MODIFIERS + r"(class|interface|struct|enum|trait|namespace|object|record|"
    r"protocol|extension|union|mod|module|type)\s+(?!(?:class|struct)\b)([A-Za-z_$][\w$.]*)")
_IMPL = re.compile(r"^\s*(?:unsafe\s+)?impl\b(?:\s*<[^>]*>)?\s+([\w:]+)(?:<[^>]*>)?"
                   r"(?:\s+for\s+([\w:]+))?")
_VARIABLE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:const|let|var|val)\s+([A-Za-z_$][\w$]*)")
_FIELD_FUNCTION = re.compile(
    r"^\s*(?:(?:static|readonly|private|public|protected|async)\s+)*([A-Za-z_$][\w$]*)\s*"
    r"(?::[^=]*)?=\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*(?::[^=]*)?=>|[A-Za-z_$][\w$]*\s*=>)")
_C_LIKE = re.compile(
    r"^\s*((?:[\w$<>\[\]?,.*&:~@]+\s+)*?)(~?[A-Za-z_$][\w$]*(?:::~?[A-Za-z_$][\w$]*)*)\s*"
    r"(?:<[^<>()]*>)?\s*\(")
# Words that come before a call or another statement, not before a definition.
_STATEMENT_WORDS = {"export", "default", "return", "await", "new", "throw", "yield", "else",
                    "case", "typeof", "delete", "do", "echo", "print", "go", "defer"}
_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "new", "sizeof", "else", "do",
             "try", "synchronized", "using", "lock", "foreach", "when", "match", "with",
             "function", "assert", "static_assert", "typeof", "await", "throw"}
_TYPES = {"class", "interface", "struct", "enum", "trait", "namespace", "object", "record",
          "protocol", "extension", "union", "mod", "module", "impl"}
# Lines that belong to the definition below them: annotations, attributes, templates.
_ANNOTATION = re.compile(r"^\s*(?:@|#\[|\[[A-Za-z]|template\s*<)")


def _bracket_definitions(lines: list[str], language: str) -> list[_Definition] | None:
    scanned = _scan(lines, language)
    if scanned is None:
        return None
    return _bracket_level(lines, scanned, 0, len(lines), 0)


def _bracket_level(lines: list[str], scanned: _Lines, start: int, end: int,
                   depth: int) -> list[_Definition]:
    """The definitions among the statements at ``depth`` between ``start`` and ``end``."""
    definitions: list[_Definition] = []
    floor = start  # where the previous definition ended
    annotated: int | None = None  # where the annotations right above this statement start

    def comment_or_annotation(index: int) -> bool:
        return not scanned.code[index] or bool(_ANNOTATION.match(lines[index]))

    index = start
    while index < end:
        if scanned.starts[index] != depth or not scanned.code[index]:
            if not lines[index].strip():
                annotated = None
            index += 1
            continue
        last = index
        while last + 1 < end and (scanned.ends[last] > depth or _continues(lines, last)):
            last += 1
        found = _name(lines[index:last + 1], scanned.code[index:last + 1], inside=depth > 0)
        if found is None and _ANNOTATION.match(lines[index]):
            # An annotation on lines of its own, such as @Override or #[test].
            if annotated is None:
                annotated = _attach(lines, index, floor, comment_or_annotation)
        # One line on its own (a constant, a field, a one-line getter) is no definition.
        elif found is not None and last > index:
            name, is_type = found
            first = annotated if annotated is not None else _attach(
                lines, index, floor, comment_or_annotation)
            members = _bracket_level(lines, scanned, index, last + 1, depth + 1) if is_type else []
            definitions.append(_Definition(first, last + 1, name, members))
            floor = last + 1
            annotated = None
        else:
            annotated = None
        index = last + 1
    return definitions


def _continues(lines: list[str], index: int) -> bool:
    """Whether the statement on this line goes on below, at the same depth."""
    line = re.sub(r"\s//.*$", "", lines[index]).rstrip()
    following = lines[index + 1].lstrip()
    if not following:
        return False
    return (line.endswith(("=", ",", "+", "&&", "||", "?", ".", "=>", "->"))
            or following.startswith(("{", ".", "?.", ")", "]", ":", "&&", "||", "?", "->",
                                      "where ", "throws ", "extends ", "implements ")))


def _name(unit: list[str], code: list[bool], inside: bool) -> tuple[str, bool] | None:
    """What a statement defines and whether it is a type; None when it defines nothing."""
    signature = next((line for line, has_code in zip(unit, code, strict=True)
                      if has_code and not _ANNOTATION.match(line)), "")
    if match := _FUNCTION.match(signature):
        receiver, name = match.groups()
        return (f"{receiver}.{name}" if receiver else name), False
    if match := _IMPL.match(signature):
        return match.group(2) or match.group(1), True
    if match := _TYPE.match(signature):
        return match.group(2), match.group(1) != "type"
    if match := _VARIABLE.match(signature):
        return match.group(1), False
    if inside and (match := _FIELD_FUNCTION.match(signature)):
        return match.group(1), False
    if match := _C_LIKE.match(signature):
        words = set(match.group(1).split())
        name = match.group(2)
        if name in _KEYWORDS or (words and words <= _STATEMENT_WORDS):
            return None
        if words or inside or "::" in name:
            return name, False
    return None
