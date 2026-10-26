from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import quote

from pydantic import BaseModel, TypeAdapter

M = TypeVar("M", bound=BaseModel)


class Unset:
    """An argument that was not given: the API's default applies (unlike None, which is null)."""

    _instance: "Unset | None" = None

    def __new__(cls) -> "Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNSET"


UNSET = Unset()


def _path(value: Any) -> str:
    """A path parameter, encoded: a project named "my docs" is my%20docs."""
    return quote(str(value), safe="")


def _body(model: type[BaseModel], fields: dict[str, Any], *, optional: bool = False) -> Any:
    """The JSON body of the fields given, checked against the request model first.

    Fields left UNSET are not sent, so the server's defaults apply; None is sent as null.
    """
    given = {name: value for name, value in fields.items() if value is not UNSET}
    if optional and not given:
        return None
    return model.model_validate(given).model_dump(mode="json", by_alias=True, exclude_unset=True)


def _none(data: Any) -> None:
    """The result of an operation that answers with no content."""
    return None


def _bytes(data: bytes) -> bytes:
    """The result of an operation that answers with a file: its bytes, not JSON."""
    return data


def _raw(data: Any) -> Any:
    """A result the schema does not describe with a model: the JSON as it came."""
    return data


def _list(model: type[M]) -> Callable[[Any], list[M]]:
    """Reads a JSON list of ``model``."""
    adapter = TypeAdapter(list[model])  # type: ignore[valid-type]
    return adapter.validate_python
