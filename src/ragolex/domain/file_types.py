"""The file types documents can be read from, by extension and content type."""

from pathlib import PurePath

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

CONTENT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
    ".docx": DOCX,
}

# What clients send when they don't know a file's type.
_GENERIC = {"", "application/octet-stream"}
# Other names for the same types.
_ALIASES = {"text/x-markdown": "text/markdown", "application/xhtml+xml": "text/html"}


def content_type_for(file_name: str, declared: str | None) -> str | None:
    """The content type of an upload: the declared one, or the extension's.

    Browsers often send no type, or a generic one, for Markdown files;
    the extension decides then.
    """
    declared = (declared or "").split(";")[0].strip().lower()
    if declared in _GENERIC:
        return CONTENT_TYPES.get(PurePath(file_name).suffix.lower(), declared or None)
    return _ALIASES.get(declared, declared)


# How many of a file's first bytes decide whether its content fits its type.
HEAD_BYTES = 8192
ZIP_SIGNATURE = b"PK\x03\x04"
# Bytes text is made of: everything but the control characters, except whitespace.
_TEXT_BYTES = bytes(range(32, 256)) + b"\t\n\x0c\r"


def content_mismatch(content_type: str, head: bytes) -> str | None:
    """Why a file's first bytes do not fit ``content_type``; None when they do.

    The declared type and the file name are the client's word: a program
    renamed ``notes.txt`` or a text file renamed ``report.pdf`` is refused
    here, before any reader opens it. PDF readers find the header within
    the first kilobyte; Word documents are ZIP archives. Text must not be
    binary: not a PDF or a ZIP archive, which can start like text, and not
    more than a tenth control characters, as programs, images and UTF-16
    text are (a stray NUL in a text file is dropped when it is read).
    """
    if content_type == "application/pdf":
        return None if b"%PDF-" in head[:1024] else "it is not a PDF"
    if content_type == DOCX:
        return None if head.startswith(ZIP_SIGNATURE) else "it is not a Word document"
    if content_type.startswith("text/"):
        if head.lstrip().startswith(b"%PDF-"):
            return "it is a PDF, not text"
        if head.startswith(ZIP_SIGNATURE):
            return "it is a ZIP archive or an Office file, not text"
        if len(head.translate(None, delete=_TEXT_BYTES)) * 10 > len(head):
            return "it is binary, not text"
    return None
