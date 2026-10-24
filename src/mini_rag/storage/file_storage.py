"""Storage of uploaded files on the local file system.

All path handling lives here, including the checks that keep every path
inside the storage root, so no other layer builds file paths itself. With
encryption keys, files are written encrypted (see core.encryption), and
readers get a decrypted copy for as long as they need it.
"""

import os
import re
import secrets
import shutil
import string
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mini_rag.core.config import Settings
from mini_rag.core.encryption import (
    HEADER_BYTES,
    EncryptionError,
    FileEncryptor,
    KeyRing,
    file_key_id,
    is_encrypted_file,
)
from mini_rag.core.errors import FileNotFound

_KEY_ALPHABET = string.ascii_lowercase + string.digits
_KEY_LENGTH = 12


def clean_file_name(name: str) -> str:
    """Make a user-supplied file name safe: spaces become '_', and only
    word characters and '.' are kept."""
    cleaned = re.sub(r"[^\w.]", "", name.strip().replace(" ", "_"))
    return cleaned or "file"


def _random_key() -> str:
    return "".join(secrets.choice(_KEY_ALPHABET) for _ in range(_KEY_LENGTH))


class FileStorage:

    def __init__(self, root: Path, keys: KeyRing | None = None):
        self.root = Path(root).resolve()
        self.keys = keys

    @classmethod
    def from_settings(cls, settings: Settings) -> "FileStorage":
        return cls(root=settings.FILES_DIR, keys=settings.encryption_keys)

    def encryptor(self) -> FileEncryptor | None:
        """What new files are encrypted with as they are written; None stores them as they are."""
        return self.keys.file_encryptor() if self.keys else None

    @contextmanager
    def plaintext(self, path: Path) -> Iterator[Path]:
        """A stored file as its readers need it.

        That is the file itself, or, when it is encrypted, a decrypted copy
        in a private temporary folder, removed again afterwards. Raises
        EncryptionError when it cannot be decrypted.
        """
        if not self.is_encrypted(path):
            yield path
            return
        with tempfile.TemporaryDirectory(prefix="mini-rag-") as folder:
            copy = Path(folder) / path.name
            self._decrypt(path, copy)
            yield copy

    def copy_plaintext(self, path: Path, target: Path) -> None:
        """Copy a stored file to ``target`` as it was uploaded, decrypted if need be."""
        if self.is_encrypted(path):
            self._decrypt(path, target)
        else:
            shutil.copyfile(path, target)

    @staticmethod
    def is_encrypted(path: Path) -> bool:
        with path.open("rb") as file:
            return is_encrypted_file(file.read(HEADER_BYTES))

    @staticmethod
    def key_id(path: Path) -> str | None:
        """The id of the key a stored file is encrypted with; None if it is not encrypted."""
        with path.open("rb") as file:
            return file_key_id(file.read(HEADER_BYTES))

    def encrypt_file(self, path: Path) -> bool:
        """Encrypt a stored file with the current key, unless it already is.

        A file encrypted with an older key is encrypted again with the
        current one. The file is replaced in one step, so it is never left
        half-written. Returns whether it changed.
        """
        keys = self._keys()
        current = self.key_id(path)
        if current == keys.current_id:
            return False
        encryptor = keys.file_encryptor()
        temporary = path.with_name(f".{path.name}.encrypting")
        try:
            with path.open("rb") as source, temporary.open("wb") as out:
                out.write(encryptor.header)
                pieces = keys.decrypt_stream(source) if current else iter(
                    lambda: source.read(1024 * 1024), b"")
                for piece in pieces:
                    out.write(encryptor.update(piece))
                out.write(encryptor.finish())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return True

    def stored_files(self) -> Iterator[Path]:
        """Every stored file, in every project folder."""
        if not self.root.is_dir():
            return
        for directory in sorted(self.root.iterdir()):
            if directory.is_dir():
                yield from sorted(path for path in directory.iterdir()
                                  if path.is_file() and not path.name.startswith("."))

    def _decrypt(self, path: Path, target: Path) -> None:
        keys = self._keys()
        with path.open("rb") as source, target.open("wb") as out:
            for piece in keys.decrypt_stream(source):
                out.write(piece)

    def _keys(self) -> KeyRing:
        if self.keys is None:
            raise EncryptionError("files are encrypted, but ENCRYPTION_KEYS is empty")
        return self.keys

    def reserve_file(self, project_id: str, original_name: str) -> tuple[str, Path]:
        """Create an empty file with a unique ID in the project folder.

        Creating the file (rather than only checking that the name is free)
        makes the reservation atomic, so concurrent uploads never collide.
        """
        directory = self._project_dir(project_id)
        directory.mkdir(parents=True, exist_ok=True)
        name = clean_file_name(original_name)

        while True:
            file_id = f"{_random_key()}_{name}"
            path = directory / file_id
            try:
                path.touch(exist_ok=False)
            except FileExistsError:
                continue
            return file_id, path

    def get_file_path(self, project_id: str, file_id: str) -> Path:
        """Return the path of a stored file, or raise FileNotFound.

        The resolved path must sit directly inside the project folder, so IDs
        such as '..', absolute paths or symlinks can never reach other files.
        """
        directory = self._project_dir(project_id)
        path = (directory / file_id).resolve()
        if path.parent != directory or not path.is_file():
            raise FileNotFound()
        return path

    def delete_file(self, project_id: str, file_id: str) -> None:
        """Remove a stored file; nothing happens if it is already gone."""
        directory = self._project_dir(project_id)
        path = (directory / file_id).resolve()
        if path.parent != directory:
            raise FileNotFound()
        path.unlink(missing_ok=True)

    def delete_project(self, project_id: str) -> None:
        """Remove a project's folder with all its files; nothing happens if there is none."""
        directory = self._project_dir(project_id)
        if directory.is_dir():
            shutil.rmtree(directory)

    def _project_dir(self, project_id: str) -> Path:
        directory = (self.root / project_id).resolve()
        if directory.parent != self.root:
            raise ValueError(f"Invalid project id: {project_id!r}")
        return directory
