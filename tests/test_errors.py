import asyncio
import json

import pytest
from starlette.requests import Request

from ragolex.api.error_handlers import handle_app_error
from ragolex.core.errors import (
    AppError,
    FileNotFound,
    FileTooLarge,
    NoTextExtracted,
    ProcessingFailed,
    ProjectNotFound,
    UnsupportedFileType,
    UploadFailed,
)

ERRORS = [FileNotFound, FileTooLarge, NoTextExtracted, ProcessingFailed,
          ProjectNotFound, UnsupportedFileType, UploadFailed]


def call_handler(error: AppError):
    request = Request({"type": "http", "method": "POST", "path": "/x", "headers": []})
    response = asyncio.run(handle_app_error(request, error))
    return response.status_code, json.loads(response.body)


@pytest.mark.parametrize("error_class", ERRORS)
def test_handler_returns_signal_and_status(error_class):
    status_code, body = call_handler(error_class())

    assert status_code == error_class.status_code
    assert body == {"signal": error_class.signal.value}


def test_every_error_has_its_own_signal():
    signals = [error_class.signal for error_class in ERRORS]

    assert len(set(signals)) == len(signals)


def test_detail_is_not_leaked_to_clients():
    _, body = call_handler(ProcessingFailed("stack trace with /secret/path"))

    assert body == {"signal": "processing_failed"}


def test_client_errors_with_a_cause_are_logged_as_warnings(caplog):
    error = ProcessingFailed("Could not read x.pdf")
    error.__cause__ = ValueError("bad xref table")

    with caplog.at_level("WARNING", logger="ragolex.api.error_handlers"):
        call_handler(error)

    assert "bad xref table" in caplog.text
