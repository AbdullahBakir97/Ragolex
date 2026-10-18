from collections.abc import Mapping
from pathlib import PurePath

from mini_rag.core.errors import UnsupportedFileType
from mini_rag.domain.file_types import CODE_LANGUAGES

from .base import DocumentLoader
from .code_loader import CodeLoader
from .docx_loader import DocxLoader
from .html_loader import HtmlLoader
from .markdown_loader import MarkdownLoader
from .pdf_loader import PdfLoader
from .text_loader import TextLoader


class LoaderRegistry:
    """Chooses a document loader by file extension (case-insensitive).

    Supporting a new file type means registering a loader here; nothing
    that uses the registry has to change.
    """

    def __init__(self, loaders: Mapping[str, DocumentLoader]):
        self._loaders = {extension.lower(): loader for extension, loader in loaders.items()}

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset(self._loaders)

    def get(self, file_name: str) -> DocumentLoader:
        extension = PurePath(file_name).suffix.lower()
        try:
            return self._loaders[extension]
        except KeyError:
            raise UnsupportedFileType() from None


def default_loader_registry() -> LoaderRegistry:
    markdown, html = MarkdownLoader(), HtmlLoader()
    code = {language: CodeLoader(language) for language in set(CODE_LANGUAGES.values())}
    return LoaderRegistry({
        **{extension: code[language] for extension, language in CODE_LANGUAGES.items()},
        ".txt": TextLoader(),
        ".md": markdown,
        ".markdown": markdown,
        ".html": html,
        ".htm": html,
        ".pdf": PdfLoader(),
        ".docx": DocxLoader(),
    })
