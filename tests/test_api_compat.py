"""tools/api_compat.py: which schema changes break the API's clients."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("api_compat", ROOT / "tools" / "api_compat.py")
api_compat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api_compat)


def spec():
    """A small API: a search with a body, a query parameter and a response."""
    return {
        "paths": {
            "/items/{id}": {
                "post": {
                    "parameters": [
                        {"in": "path", "name": "id", "required": True, "schema": {"type": "string"}},
                        {"in": "query", "name": "limit", "required": False,
                         "schema": {"type": "integer", "maximum": 100}},
                    ],
                    "requestBody": {"required": True, "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/Request"}}}},
                    "responses": {"200": {"content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/Response"}}}}},
                },
            },
        },
        "components": {"schemas": {
            "Request": {"type": "object", "required": ["query"], "properties": {
                "query": {"type": "string", "maxLength": 2000},
                "mode": {"type": "string", "enum": ["hybrid", "vector"]},
                "tags": {"type": "array", "items": {"type": "string"}},
            }},
            "Response": {"type": "object", "required": ["signal", "items"], "properties": {
                "signal": {"type": "string", "enum": ["ok"]},
                "items": {"type": "array", "items": {"$ref": "#/components/schemas/Item"}},
            }},
            "Item": {"type": "object", "required": ["id", "score"], "properties": {
                "id": {"type": "string"},
                "score": {"type": "number"},
            }},
        }},
    }


def changed(edit):
    new = copy.deepcopy(spec())
    edit(new)
    return api_compat.breaking_changes(spec(), new)


OP = ("paths", "/items/{id}", "post")


def op(s):
    return s["paths"]["/items/{id}"]["post"]


def schemas(s):
    return s["components"]["schemas"]


def test_growing_the_api_breaks_nothing():
    def grow(s):
        op(s)["parameters"].append({"in": "query", "name": "tag", "required": False,
                                    "schema": {"type": "string"}})
        op(s)["parameters"][1]["schema"]["maximum"] = 500
        schemas(s)["Request"]["properties"]["top_k"] = {"type": "integer", "default": 5}
        schemas(s)["Request"]["properties"]["query"]["maxLength"] = 4000
        schemas(s)["Request"]["properties"]["mode"]["enum"].append("keyword")
        schemas(s)["Response"]["properties"]["signal"]["enum"].append("partial")
        schemas(s)["Item"]["properties"]["page"] = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
        s["paths"]["/other"] = {"get": {"responses": {"200": {}}}}

    assert changed(grow) == []
    assert api_compat.breaking_changes(spec(), spec()) == []


@pytest.mark.parametrize(("edit", "message"), [
    (lambda s: s["paths"].pop("/items/{id}"), "POST /items/{id}: was removed"),
    (lambda s: op(s)["parameters"].append({"in": "query", "name": "tag", "required": True,
                                          "schema": {"type": "string"}}),
     "query parameter tag: is new and required"),
    (lambda s: op(s)["parameters"][1].update(required=True), "parameter limit: is now required"),
    (lambda s: op(s)["parameters"][1]["schema"].update(maximum=50), "maximum fell to 50"),
    (lambda s: schemas(s)["Request"]["required"].append("mode"), "body.mode: is now required"),
    (lambda s: schemas(s)["Request"]["properties"]["mode"]["enum"].remove("vector"),
     "body.mode: no longer accepts vector"),
    (lambda s: schemas(s)["Request"]["properties"]["query"].update(maxLength=500),
     "body.query: maxLength fell to 500"),
    (lambda s: schemas(s)["Request"]["properties"]["query"].update(pattern="^[a-z]+$"),
     "body.query: pattern changed"),
    (lambda s: schemas(s)["Request"]["properties"]["tags"]["items"].update(type="integer"),
     "body.tags[]: no longer accepts string"),
    (lambda s: schemas(s)["Item"]["properties"].pop("score"), "response.items[].score: was removed"),
    (lambda s: schemas(s)["Item"]["required"].remove("score"),
     "response.items[].score: may now be missing"),
    (lambda s: schemas(s)["Item"]["properties"].update(
        score={"anyOf": [{"type": "number"}, {"type": "null"}]}),
     "response.items[].score: may now be null"),
    (lambda s: op(s)["responses"].update({"201": op(s)["responses"].pop("200")}),
     "answers 201 instead of 200"),
])
def test_breaking_changes_are_found(edit, message):
    changes = changed(edit)

    assert any(message in change for change in changes), changes


def test_a_new_required_body_is_breaking():
    def add_body(s):
        s["paths"]["/other"] = {"get": {"responses": {"200": {}}}}

    old = copy.deepcopy(spec())
    add_body(old)
    new = copy.deepcopy(old)
    new["paths"]["/other"]["get"]["requestBody"] = {"required": True, "content": {
        "application/json": {"schema": {"type": "object", "properties": {}}}}}

    assert api_compat.breaking_changes(old, new) == ["GET /other body: is new and required"]


def test_the_command_reports_and_fails(tmp_path, capsys):
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    old.write_text(json.dumps(spec()))
    broken = spec()
    schemas(broken)["Item"]["properties"].pop("id")
    new.write_text(json.dumps(broken))

    assert api_compat.main([str(old), str(old)]) == 0
    assert api_compat.main([str(old), str(new)]) == 1
    assert api_compat.main([str(old)]) == 2
    out = capsys.readouterr().out
    assert "No breaking changes." in out
    assert "breaking: POST /items/{id} response.items[].id: was removed" in out


def test_the_sdks_schema_has_no_breaking_change_against_itself():
    current = json.loads((ROOT / "sdk" / "openapi.json").read_text(encoding="utf-8"))

    assert api_compat.breaking_changes(current, current) == []
