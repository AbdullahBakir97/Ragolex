import zipfile

import pytest

from ragolex.core.errors import UnsupportedFileType
from ragolex.domain.file_types import CONTENT_TYPES, content_type_for
from ragolex.loaders.code_loader import CodeLoader
from ragolex.loaders.docx_loader import DocxLoader
from ragolex.loaders.html_loader import HtmlLoader
from ragolex.loaders.markdown_loader import MarkdownLoader
from ragolex.loaders.pdf_loader import PdfLoader
from ragolex.loaders.registry import LoaderRegistry, default_loader_registry
from ragolex.loaders.text_loader import TextLoader


@pytest.mark.parametrize(("file_name", "loader_type"), [
    ("abc_notes.txt", TextLoader),
    ("abc_NOTES.TXT", TextLoader),
    ("abc_report.pdf", PdfLoader),
    ("abc_report.Pdf", PdfLoader),
    ("abc_README.md", MarkdownLoader),
    ("abc_guide.markdown", MarkdownLoader),
    ("abc_page.html", HtmlLoader),
    ("abc_page.HTM", HtmlLoader),
    ("abc_letter.docx", DocxLoader),
    ("abc_app.py", CodeLoader),
    ("abc_main.TS", CodeLoader),
    ("abc_lib.rs", CodeLoader),
])
def test_default_registry_picks_loader_by_extension(file_name, loader_type):
    assert isinstance(default_loader_registry().get(file_name), loader_type)


@pytest.mark.parametrize("file_name", ["abc_old.doc", "abc_notes", "abc_archive.txt.zip", ".."])
def test_registry_rejects_unknown_extensions(file_name):
    with pytest.raises(UnsupportedFileType):
        default_loader_registry().get(file_name)


def test_new_file_types_only_need_registering():
    class RtfLoader:
        def load(self, path, source):
            return []

    rtf = RtfLoader()
    registry = LoaderRegistry({".RTF": rtf})

    assert registry.get("x_letter.rtf") is rtf
    assert registry.extensions == {".rtf"}


def test_every_known_file_type_has_a_loader():
    assert default_loader_registry().extensions == set(CONTENT_TYPES)


@pytest.mark.parametrize(("file_name", "declared", "expected"), [
    ("notes.md", "text/markdown", "text/markdown"),
    ("notes.md", "", "text/markdown"),
    ("notes.md", None, "text/markdown"),
    ("notes.md", "application/octet-stream", "text/markdown"),
    ("notes.md", "text/x-markdown", "text/markdown"),
    ("page.html", "text/html; charset=utf-8", "text/html"),
    ("notes.md", "text/plain", "text/plain"),  # A declared type stays.
    ("archive.zip", "application/octet-stream", "application/octet-stream"),
    ("unknown", "", None),
    # For code the extension decides: browsers name these types inconsistently.
    ("app.py", "text/plain", "text/x-python"),
    ("app.ts", "video/mp2t", "text/x-typescript"),
    ("App.JSX", "", "text/javascript"),
    ("lib.h", "application/octet-stream", "text/x-c"),
])
def test_content_type_for_uses_the_extension_when_the_type_is_generic(file_name, declared,
                                                                       expected):
    assert content_type_for(file_name, declared) == expected


def test_text_loader_reads_utf8_and_replaces_bad_bytes(tmp_path):
    path = tmp_path / "a.txt"
    path.write_bytes("café ".encode() + b"\xff")

    [document] = TextLoader().load(path, source="a.txt")

    assert document.text == "café �"
    assert document.metadata == {"source": "a.txt"}


def test_pdf_loader_returns_one_document_per_page(tmp_path, make_pdf):
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf(["First page.", "", "Third page."]))

    documents = PdfLoader().load(path, source="a.pdf")

    assert [(d.text.strip(), d.metadata) for d in documents] == [
        ("First page.", {"source": "a.pdf", "page": 1}),
        ("", {"source": "a.pdf", "page": 2}),
        ("Third page.", {"source": "a.pdf", "page": 3}),
    ]


def load(loader, tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content.encode() if isinstance(content, str) else content)
    return [(d.text, d.metadata) for d in loader.load(path, source=name)]


def test_markdown_loader_returns_one_document_per_section(tmp_path):
    text = """---
title: Handbook
---
Read this first.

# Handbook

## Leave
You get 25 days.

### Carry-over
Up to 5 days.

```bash
# not a heading
```

Expenses
--------
Submit receipts within 30 days.
- an item
---
"""
    documents = load(MarkdownLoader(), tmp_path, "h.md", text)

    assert documents == [
        ("Read this first.", {"source": "h.md"}),
        ("## Leave\n\nYou get 25 days.", {"source": "h.md", "section": "Handbook > Leave"}),
        ("### Carry-over\n\nUp to 5 days.\n\n```bash\n# not a heading\n```",
         {"source": "h.md", "section": "Handbook > Leave > Carry-over"}),
        ("## Expenses\n\nSubmit receipts within 30 days.\n- an item\n---",
         {"source": "h.md", "section": "Handbook > Expenses"}),
    ]


def test_html_loader_keeps_readable_text_by_section(tmp_path):
    html = """<!doctype html><html><head><title>Team  handbook</title>
<style>p { color: red }</style><script>var leave = 99;</script>
<body><nav><a href="/">Home</a></nav>
<h1>Hand<b>book</b></h1><p>Welcome to the
  <em>team</em> &amp; enjoy.<p>No closing tag<br>and a line break
<h2>Leave</h2><ul><li>25 days<li>5 carried over</ul>
<table><tr><th>Days</th><th>Who</th></tr><tr><td>25</td><td>Everyone</td></tr></table>
<div hidden>secret</div><pre>  keep
    spacing</pre>
<footer>(c) 2026</footer></body></html>"""

    documents = load(HtmlLoader(), tmp_path, "h.html", html)

    meta = {"source": "h.html", "title": "Team handbook"}
    assert documents == [
        ("# Handbook\n\nWelcome to the team & enjoy.\n\nNo closing tag\n\nand a line break",
         {**meta, "section": "Handbook"}),
        ("## Leave\n\n- 25 days\n\n- 5 carried over\n\nDays | Who\n\n25 | Everyone"
         "\n\n  keep\n    spacing", {**meta, "section": "Handbook > Leave"}),
    ]


def test_html_loader_without_a_title_or_headings(tmp_path):
    assert load(HtmlLoader(), tmp_path, "p.htm", "<p>Just text</p></div>") == [
        ("Just text", {"source": "p.htm"})]


def p(text, style=None, numbered=False):
    properties = ""
    if style or numbered:
        properties = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + (
            "<w:numPr/>" if numbered else "") + "</w:pPr>"
    return f"<w:p>{properties}<w:r><w:t>{text}</w:t></w:r></w:p>"


def test_docx_loader_returns_one_document_per_section(tmp_path, make_docx):
    styles = ('<w:style w:styleId="berschrift1"><w:name w:val="heading 1"/></w:style>'
              '<w:style w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>'
              '<w:style w:styleId="Quote"><w:name w:val="Quote"/></w:style>')
    body = (
        p("Intro text.")
        + p("Leave", "berschrift1")
        + "<w:p><w:r><w:t>You get </w:t></w:r><w:r><w:t>25 days.</w:t><w:br/>"
          "<w:t>Ask early.</w:t></w:r><w:r><w:delText>deleted</w:delText></w:r></w:p>"
        + p("Plan ahead", numbered=True)
        + p("   ")
        + p("Table", "Heading2")
        + "<w:tbl><w:tr><w:tc>" + p("Days") + "</w:tc><w:tc>" + p("Who") + "</w:tc></w:tr>"
          "<w:tr><w:tc>" + p("25") + "</w:tc><w:tc>" + p("All") + "</w:tc></w:tr></w:tbl>"
        + p("A quote", "Quote")
    )

    documents = load(DocxLoader(), tmp_path, "h.docx", make_docx(body, styles))

    assert documents == [
        ("Intro text.", {"source": "h.docx"}),
        ("# Leave\n\nYou get 25 days.\nAsk early.\n\n- Plan ahead",
         {"source": "h.docx", "section": "Leave"}),
        ("## Table\n\nDays | Who\n\n25 | All\n\nA quote",
         {"source": "h.docx", "section": "Leave > Table"}),
    ]


def test_docx_loader_rejects_a_dtd(tmp_path):
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')

    with pytest.raises(ValueError, match="DTD"):
        DocxLoader().load(path, source="bomb.docx")


def test_docx_loader_rejects_a_file_that_is_not_a_word_document(tmp_path):
    path = tmp_path / "fake.docx"
    path.write_text("not a zip")

    with pytest.raises(zipfile.BadZipFile):
        DocxLoader().load(path, source="fake.docx")
