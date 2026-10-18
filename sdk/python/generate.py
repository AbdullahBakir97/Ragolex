"""Generate the client's models and operations from the API's OpenAPI schema.

    python generate.py            # from ../openapi.json
    python generate.py --check    # fail if the generated files are out of date

Writes src/mini_rag_client/models.py (a Pydantic model per schema) and
src/mini_rag_client/_operations.py (a method per operation, sync and async).
"""

import argparse
import json
import keyword
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = HERE.parent / "openapi.json"
PACKAGE = HERE / "src" / "mini_rag_client"
HEADER = '"""Generated from sdk/openapi.json by sdk/python/generate.py: do not edit."""\n'

# Written by hand in client.py: a multipart upload, Server-Sent Events, and
# JSON-RPC, which an MCP client speaks better.
CUSTOM = {"upload_data", "ask_project_stream", "widget_ask", "mcp_endpoint"}


def ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def class_name(name: str) -> str:
    """A schema's name as a class name: Body_upload_data becomes BodyUploadData."""
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", name) if part)


def identifier(name: str) -> str:
    name = re.sub(r"\W", "_", name)
    return f"{name}_" if keyword.iskeyword(name) or name in {"self", "json", "model_config"} else name


class Types:
    """Python annotations for JSON Schemas."""

    def __init__(self, schemas: dict):
        self.schemas = schemas

    def annotation(self, schema: dict) -> str:
        if "$ref" in schema:
            return class_name(ref_name(schema["$ref"]))
        if "anyOf" in schema:
            parts = [self.annotation(part) for part in schema["anyOf"]]
            return " | ".join(dict.fromkeys(parts))
        if "const" in schema:
            return f"Literal[{schema['const']!r}]"
        if "enum" in schema:
            # Open: a value added to the API later still reads.
            return f"Literal[{', '.join(repr(v) for v in schema['enum'])}] | str"
        kind = schema.get("type")
        if kind == "string":
            return "datetime" if schema.get("format") == "date-time" else "str"
        if kind == "integer":
            return "int"
        if kind == "number":
            return "float"
        if kind == "boolean":
            return "bool"
        if kind == "null":
            return "None"
        if kind == "array":
            return f"list[{self.annotation(schema.get('items', {}))}]"
        if kind is None:
            return "Any"  # e.g. a validation error's input: anything
        if kind == "object":
            extra = schema.get("additionalProperties")
            value = self.annotation(extra) if isinstance(extra, dict) and extra else "Any"
            return f"dict[str, {value}]"
        raise ValueError(f"No annotation for {schema}")

    def accepts(self, schema: dict) -> str:
        """An argument's annotation: models may also be given as dicts."""
        text = self.annotation(schema)
        return re.sub(r"\b([A-Z]\w+)\b(?!\[)",
                      lambda m: f"{m.group(1)} | dict[str, Any]" if m.group(1) in self.models else m.group(1),
                      text)

    @property
    def models(self) -> set[str]:
        return {class_name(n) for n, s in self.schemas.items() if s.get("type") == "object"}


def default_repr(value) -> str:
    return repr(value)


def models_module(schemas: dict) -> str:
    types = Types(schemas)
    lines = [HEADER, "from __future__ import annotations\n", "from datetime import datetime",
             "from typing import Any, Literal\n", "from pydantic import BaseModel, ConfigDict, Field\n",
             "", "class Model(BaseModel):",
             '    """Fields the API adds later are kept, so older clients still read newer servers."""\n',
             '    model_config = ConfigDict(extra="allow", populate_by_name=True)\n']
    names = []
    for name, schema in schemas.items():
        cls = class_name(name)
        if "enum" in schema:
            lines += ["", f"{cls} = {types.annotation(schema)}"]
            if schema.get("description"):
                lines.append(f'"""{schema["description"]}"""')
            continue
        names.append(cls)
        lines += ["", "", f"class {cls}(Model):"]
        if schema.get("description"):
            lines.append(f'    """{schema["description"]}"""\n')
        required = set(schema.get("required", []))
        properties = schema.get("properties", {})
        if not properties:
            lines.append("    pass")
        for prop, prop_schema in properties.items():
            attr = identifier(prop)
            annotation = types.annotation(prop_schema)
            args = []
            if prop not in required:
                if "default" in prop_schema:
                    default = prop_schema["default"]
                    args.append(f"default_factory=lambda: {default!r}" if isinstance(default, (list, dict))
                                else f"default={default!r}")
                else:
                    args.append("default=None")
                    if "None" not in annotation.split(" | "):
                        annotation += " | None"
            if attr != prop:
                args.append(f"alias={prop!r}")
            if prop_schema.get("description"):
                args.append(f"description={prop_schema['description']!r}")
            value = f" = Field({', '.join(args)})" if args else ""
            lines.append(f"    {attr}: {annotation}{value}")
    lines += ["", "", f"for _model in ({', '.join(names)},):", "    _model.model_rebuild()", ""]
    return "\n".join(lines)


def operations_module(spec: dict) -> str:
    schemas = spec["components"]["schemas"]
    types = Types(schemas)
    sync_methods, async_methods = [], []
    for path, operations in spec["paths"].items():
        for method, op in operations.items():
            name = op["operationId"]
            if name in CUSTOM:
                continue
            params = op.get("parameters", [])
            path_params = [p for p in params if p["in"] == "path"]
            query_params = [p for p in params if p["in"] == "query"]
            signature = ["self"] + [f"{identifier(p['name'])}: {types.annotation(p['schema'])}"
                                    for p in path_params]
            keywords = []
            body_model, body_fields, body_optional = None, [], False
            body = op.get("requestBody")
            if body:
                schema = body["content"]["application/json"]["schema"]
                if "anyOf" in schema:
                    body_optional = True
                    schema = next(s for s in schema["anyOf"] if "$ref" in s)
                body_model = ref_name(schema["$ref"])
                model = schemas[body_model]
                required = set(model.get("required", []))
                for prop, prop_schema in model.get("properties", {}).items():
                    body_fields.append(prop)
                    annotation = types.accepts(prop_schema)
                    if prop in required and not body_optional:
                        keywords.append((0, f"{identifier(prop)}: {annotation}"))
                    else:
                        keywords.append((1, f"{identifier(prop)}: {annotation} | Unset = UNSET"))
            for p in query_params:
                annotation = types.annotation(p["schema"])
                if p.get("required"):
                    keywords.append((0, f"{identifier(p['name'])}: {annotation}"))
                else:
                    if "None" not in annotation.split(" | "):
                        annotation += " | None"
                    keywords.append((1, f"{identifier(p['name'])}: {annotation} = None"))
            names = [p["name"] for p in params] + body_fields
            if len(names) != len(set(names)):
                raise ValueError(f"{name}: a parameter and a body field share a name")
            keywords.sort(key=lambda k: k[0])
            if keywords:
                signature += ["*"] + [k for _, k in keywords]

            ok = next(code for code in op["responses"] if code.startswith("2"))
            media = op["responses"][ok].get("content", {})
            content = media.get("application/json", {})
            result = content.get("schema", {})
            if media and "application/json" not in media:
                # A file, such as a ZIP archive: its bytes as they came.
                returns, parse = "bytes", "_bytes"
            elif ok == "204" or not result:
                returns, parse = "None", "_none"
            elif "$ref" in result:
                returns = class_name(ref_name(result["$ref"]))
                parse = f"{returns}.model_validate"
            elif result.get("type") == "array" and "$ref" in result.get("items", {}):
                item = class_name(ref_name(result["items"]["$ref"]))
                returns, parse = f"list[{item}]", f"_list({item})"
            else:
                returns, parse = types.annotation(result), "_raw"

            url = path
            for p in path_params:
                url = url.replace("{" + p["name"] + "}", "{_path(" + identifier(p["name"]) + ")}")
            query = ", ".join(f"{p['name']!r}: {identifier(p['name'])}" for p in query_params)
            body_arg = "None"
            if body_model:
                fields = ", ".join(f"{f!r}: {identifier(f)}" for f in body_fields)
                body_arg = f"_body({class_name(body_model)}, {{{fields}}}, optional={body_optional})"
            doc = op.get("summary", name)
            if op.get("description"):
                doc += "\n\n" + op["description"]
            doc_lines = "\n".join(("        " + line).rstrip() for line in doc.splitlines())
            target_url = f"f{url!r}" if path_params else repr(url)
            call = (f"self._request({method.upper()!r}, {target_url}, query={{{query}}}, json={body_arg}, "
                    f"response={parse})")
            head = f"def {name}(\n        " + ",\n        ".join(signature) + f",\n    ) -> {returns}:"
            for target, prefix, awaiting in ((sync_methods, "", ""), (async_methods, "async ", "await ")):
                target.append(f"    {prefix}{head}\n        \"\"\"{doc_lines.strip()}\n        \"\"\"\n"
                              f"        return {awaiting}{call}\n")
    code = "\n".join(sync_methods + async_methods)
    defined = {class_name(name) for name in schemas}
    used = sorted(name for name in set(re.findall(r"\b[A-Z]\w*\b", code)) if name in defined)
    typing_names = ["Any"] + (["Literal"] if "Literal[" in code else [])
    imports = ["from __future__ import annotations\n"]
    if re.search(r"\bdatetime\b", code):
        imports.append("from datetime import datetime")
    imports += ["from collections.abc import Callable",
                f"from typing import {', '.join(typing_names + ['TypeVar'])}\n",
                "from ._types import UNSET, Unset, _body, _bytes, _list, _none, _path, _raw",
                "from .models import (", *[f"    {name}," for name in used], ")\n"]
    return "\n".join([
        HEADER,
        *imports,
        'T = TypeVar("T")\n',
        "",
        "class Operations:",
        '    """Every operation of the API, as a method named after its operationId."""\n',
        "    def _request(self, method: str, path: str, *, query: dict[str, Any], json: Any,",
        "                 response: Callable[[Any], T]) -> T:",
        "        raise NotImplementedError\n",
        "\n".join(sync_methods),
        "",
        "class AsyncOperations:",
        '    """Every operation of the API, as an async method named after its operationId."""\n',
        "    async def _request(self, method: str, path: str, *, query: dict[str, Any], json: Any,",
        "                       response: Callable[[Any], T]) -> T:",
        "        raise NotImplementedError\n",
        "\n".join(async_methods),
        "",
        "__all__ = ['AsyncOperations', 'Operations']",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the files are out of date")
    args = parser.parse_args()
    spec = json.loads(SCHEMA.read_text(encoding="utf-8"))
    outputs = {
        PACKAGE / "models.py": models_module(spec["components"]["schemas"]),
        PACKAGE / "_operations.py": operations_module(spec),
    }
    stale = [path for path, text in outputs.items()
             if not path.exists() or path.read_text(encoding="utf-8") != text]
    if args.check:
        for path in stale:
            print(f"{path.relative_to(HERE)} is out of date: run python generate.py", file=sys.stderr)
        return 1 if stale else 0
    for path in stale:
        path.write_text(outputs[path], encoding="utf-8")
        print(f"wrote {path.relative_to(HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
