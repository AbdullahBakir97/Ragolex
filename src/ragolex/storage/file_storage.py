"""Storage of uploaded files on the local file system.

All path handling lives here, including the checks that keep every path
inside the storage root, so no other layer builds file paths itself.
"""

import re
import secrets
import shutil
import string
from pathlib import Path

from ragolex.core.errors import FileNotFound

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

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

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
