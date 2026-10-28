import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def schema(client):
    return client.get("/openapi.json").json()


def response_schema(schema, path, status):
    content = schema["paths"][path]["post"]["responses"][status]["content"]
    return content["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]


def test_app_metadata_comes_from_settings(schema):
    assert schema["info"]["title"] == "Ragolex-test"
    assert schema["info"]["version"] == "0.0.1"


def test_schema_names_the_author_and_license(schema):
    assert schema["info"]["contact"]["name"] == "Abdullah Bakir"
    assert schema["info"]["license"]["identifier"] == "AGPL-3.0-only"


def test_success_responses_are_documented(schema):
    assert response_schema(schema, "/api/v1/data/upload/{project_id}", "200") == "UploadResponse"
    assert response_schema(schema, "/api/v1/data/process/{project_id}", "200") == "ProcessResponse"


def test_error_responses_are_documented_with_their_signals(schema):
    upload = schema["paths"]["/api/v1/data/upload/{project_id}"]["post"]["responses"]
    process = schema["paths"]["/api/v1/data/process/{project_id}"]["post"]["responses"]

    assert response_schema(schema, "/api/v1/data/process/{project_id}", "404") == "ErrorResponse"
    assert "file_not_found" in process["404"]["description"]
    assert "file_size_exceeded" in str(upload) and "file_type_not_supported" in str(upload)
    assert "processing_failed" in str(process) and "file_has_no_text" in str(process)


def test_project_id_rules_are_documented(schema):
    params = schema["paths"]["/api/v1/data/upload/{project_id}"]["post"]["parameters"]
    [project_id] = [p for p in params if p["name"] == "project_id"]

    assert project_id["schema"]["pattern"] == "^[A-Za-z0-9_-]{1,64}$"


def test_index_endpoint_is_documented(schema):
    responses = schema["paths"]["/api/v1/index/{project_id}"]["post"]["responses"]

    assert response_schema(schema, "/api/v1/index/{project_id}", "200") == "IndexResponse"
    assert "project_not_found" in responses["404"]["description"]
    assert "file_not_found" in responses["404"]["description"]
    assert "embedding_failed" in responses["502"]["description"]
    assert "embedding_not_configured" in responses["503"]["description"]


def test_search_endpoint_is_documented(schema):
    responses = schema["paths"]["/api/v1/search/{project_id}"]["post"]["responses"]

    assert response_schema(schema, "/api/v1/search/{project_id}", "200") == "SearchResponse"
    assert "project_not_found" in responses["404"]["description"]
    assert "embedding_failed" in responses["502"]["description"]


def test_ask_endpoint_is_documented(schema):
    responses = schema["paths"]["/api/v1/ask/{project_id}"]["post"]["responses"]

    assert response_schema(schema, "/api/v1/ask/{project_id}", "200") == "AskResponse"
    assert "project_not_found" in responses["404"]["description"]
    assert "embedding_failed" in responses["502"]["description"]
    assert "llm_failed" in responses["502"]["description"]
    assert "embedding_not_configured" in responses["503"]["description"]
    assert "llm_not_configured" in responses["503"]["description"]


def test_ask_stream_endpoint_is_documented(schema):
    responses = schema["paths"]["/api/v1/ask/{project_id}/stream"]["post"]["responses"]

    assert "text/event-stream" in responses["200"]["content"]
    assert "project_not_found" in responses["404"]["description"]
    assert "llm_not_configured" in responses["503"]["description"]


def test_project_usage_endpoint_is_documented(schema):
    path = schema["paths"]["/api/v1/projects/{project_id}/usage"]["get"]

    assert path["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ProjectUsageResponse")
    assert "project_not_found" in path["responses"]["404"]["description"]
    assert "usage" in schema["components"]["schemas"]["AskResponse"]["properties"]


def test_success_examples_show_the_success_signal(schema):
    upload = schema["components"]["schemas"]["UploadResponse"]["properties"]

    assert upload["signal"]["examples"] == ["file_uploaded_successfully"]
    assert upload["file_id"]["examples"] == ["a16q20nzrtvj_notes.txt"]


def test_request_examples_look_like_real_values(schema):
    process = schema["components"]["schemas"]["ProcessRequest"]["properties"]

    assert process["file_id"]["examples"] == ["a16q20nzrtvj_notes.txt"]


def test_error_examples_show_each_signal(schema):
    process = schema["paths"]["/api/v1/data/process/{project_id}"]["post"]["responses"]
    examples = process["422"]["content"]["application/json"]["examples"]

    assert examples == {"file_has_no_text": {"value": {"signal": "file_has_no_text"}},
                        "processing_failed": {"value": {"signal": "processing_failed"}}}
    assert response_schema(schema, "/api/v1/data/process/{project_id}", "422") == "ErrorResponse"


def test_operations_are_named_after_their_route_functions(schema):
    upload = schema["paths"]["/api/v1/data/upload/{project_id}"]["post"]

    assert upload["operationId"] == "upload_data"
    assert "Body_upload_data" in schema["components"]["schemas"]


def test_the_sdks_schema_is_up_to_date(schema):
    """sdk/openapi.json is what the SDKs are generated from: regenerate both after API changes.

    Run `ragolex openapi --output sdk/openapi.json`, then see sdk/README.md.
    """
    committed = json.loads((ROOT / "sdk" / "openapi.json").read_text(encoding="utf-8"))

    assert {**committed, "info": None} == {**schema, "info": None}


def test_the_cli_writes_the_schema(tmp_path, capsys):
    from ragolex.cli import main

    assert main(["openapi", "--output", str(tmp_path / "openapi.json")]) == 0
    assert main(["openapi"]) == 0

    written = json.loads((tmp_path / "openapi.json").read_text(encoding="utf-8"))
    assert written["paths"]["/api/v1/data/upload/{project_id}"]["post"]["operationId"] == "upload_data"
    assert json.loads(capsys.readouterr().out) == written
