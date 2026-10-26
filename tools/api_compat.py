"""Find changes to the API that would break its clients, between two OpenAPI schemas.

    python tools/api_compat.py OLD.json NEW.json

Exits with 1 and lists the breaking changes when there are any (see
docs/versioning.md for the policy). Within /api/v1 the API only grows:

- an operation is never removed, and its success status never changes;
- a request never needs more than before: no new required parameter or
  body field, and a value accepted before is still accepted (types, enum
  values, lengths, ranges and patterns are never narrowed);
- a response never gives less than before: no field is removed or becomes
  optional or nullable, and no type changes. New response fields and new
  enum values in responses are allowed: clients must ignore what they do
  not know.
"""

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

METHODS = ("get", "put", "post", "delete", "patch")
# How deep to follow nested schemas; deeper ones (only recursive schemas) are not compared.
MAX_DEPTH = 30
# Request constraints that accept less when they grow, and when they shrink.
GROWING_IS_NARROWER = ("minLength", "minimum", "exclusiveMinimum", "minItems")
SHRINKING_IS_NARROWER = ("maxLength", "maximum", "exclusiveMaximum", "maxItems")


class Schemas:
    def __init__(self, spec: dict[str, Any]):
        self.components = spec.get("components", {}).get("schemas", {})

    def resolve(self, schema: dict[str, Any]) -> dict[str, Any]:
        while "$ref" in schema:
            schema = self.components[schema["$ref"].rsplit("/", 1)[-1]]
        return schema

    def variants(self, schema: dict[str, Any]) -> list[dict[str, Any]]:
        """The alternatives of a schema: anyOf/oneOf parts, resolved; itself otherwise."""
        schema = self.resolve(schema)
        parts = schema.get("anyOf") or schema.get("oneOf")
        if parts:
            return [variant for part in parts for variant in self.variants(part)]
        return [schema]


def _kinds(schemas: Schemas, schema: dict[str, Any]) -> set[str]:
    kinds = set()
    for variant in schemas.variants(schema):
        kind = variant.get("type")
        if isinstance(kind, list):
            kinds.update(kind)
        elif kind:
            kinds.add(kind)
        elif "enum" in variant or "const" in variant:
            kinds.add("string")
        else:
            kinds.add("any")
    return kinds


def _enum(schemas: Schemas, schema: dict[str, Any]) -> set[Any] | None:
    """Every value an enumeration allows; None when any value of its type is allowed."""
    values: set[Any] = set()
    for variant in schemas.variants(schema):
        if "enum" in variant:
            values.update(variant["enum"])
        elif "const" in variant:
            values.add(variant["const"])
        elif variant.get("type") != "null":
            return None
    return values


def _object(schemas: Schemas, schema: dict[str, Any]) -> dict[str, Any] | None:
    objects = [v for v in schemas.variants(schema) if v.get("type") == "object" and "properties" in v]
    return objects[0] if len(objects) == 1 else None


def _array_items(schemas: Schemas, schema: dict[str, Any]) -> dict[str, Any] | None:
    arrays = [v for v in schemas.variants(schema) if v.get("type") == "array" and "items" in v]
    return arrays[0]["items"] if len(arrays) == 1 else None


def compare_request(old_s: Schemas, new_s: Schemas, old: dict[str, Any], new: dict[str, Any],
                    where: str, depth: int = 0) -> Iterator[str]:
    """What the new schema refuses that the old one accepted."""
    if depth > MAX_DEPTH:
        return
    old_kinds, new_kinds = _kinds(old_s, old), _kinds(new_s, new)
    if "any" not in new_kinds:
        lost = old_kinds - new_kinds - ({"integer"} if "number" in new_kinds else set())
        if "any" in old_kinds or lost:
            yield f"{where}: no longer accepts {', '.join(sorted(lost or {'any type'}))}"
            return
    old_enum, new_enum = _enum(old_s, old), _enum(new_s, new)
    if new_enum is not None and (old_enum is None or old_enum - new_enum):
        removed = sorted(map(str, (old_enum or set()) - new_enum)) or ["values outside the enum"]
        yield f"{where}: no longer accepts {', '.join(removed)}"
    old_r, new_r = old_s.resolve(old), new_s.resolve(new)
    for key in GROWING_IS_NARROWER:
        if key in new_r and (key not in old_r or new_r[key] > old_r[key]):
            yield f"{where}: {key} rose to {new_r[key]}"
    for key in SHRINKING_IS_NARROWER:
        if key in new_r and (key not in old_r or new_r[key] < old_r[key]):
            yield f"{where}: {key} fell to {new_r[key]}"
    if new_r.get("pattern") and new_r.get("pattern") != old_r.get("pattern"):
        yield f"{where}: pattern changed to {new_r['pattern']}"
    old_obj, new_obj = _object(old_s, old), _object(new_s, new)
    if old_obj is not None and new_obj is not None:
        added_required = set(new_obj.get("required", [])) - set(old_obj.get("required", []))
        for name in sorted(added_required):
            yield f"{where}.{name}: is now required"
        for name, schema in old_obj["properties"].items():
            if name in new_obj["properties"]:
                yield from compare_request(old_s, new_s, schema, new_obj["properties"][name],
                                           f"{where}.{name}", depth + 1)
            elif new_obj.get("additionalProperties") is False:
                yield f"{where}.{name}: is no longer accepted"
    old_items, new_items = _array_items(old_s, old), _array_items(new_s, new)
    if old_items is not None and new_items is not None:
        yield from compare_request(old_s, new_s, old_items, new_items, f"{where}[]", depth + 1)


def compare_response(old_s: Schemas, new_s: Schemas, old: dict[str, Any], new: dict[str, Any],
                     where: str, depth: int = 0) -> Iterator[str]:
    """What the new schema may send that clients of the old one do not expect."""
    if depth > MAX_DEPTH:
        return
    old_kinds, new_kinds = _kinds(old_s, old), _kinds(new_s, new)
    if "any" not in old_kinds:
        gained = new_kinds - old_kinds - ({"integer"} if "number" in old_kinds else set())
        if "any" in new_kinds or gained:
            yield f"{where}: may now be {', '.join(sorted(gained or {'any type'}))}"
            return
    old_obj, new_obj = _object(old_s, old), _object(new_s, new)
    if old_obj is not None and new_obj is not None:
        new_required = set(new_obj.get("required", []))
        for name, schema in old_obj["properties"].items():
            if name not in new_obj["properties"]:
                yield f"{where}.{name}: was removed"
                continue
            if name in old_obj.get("required", []) and name not in new_required:
                yield f"{where}.{name}: may now be missing"
            yield from compare_response(old_s, new_s, schema, new_obj["properties"][name],
                                        f"{where}.{name}", depth + 1)
    old_items, new_items = _array_items(old_s, old), _array_items(new_s, new)
    if old_items is not None and new_items is not None:
        yield from compare_response(old_s, new_s, old_items, new_items, f"{where}[]", depth + 1)


def _success(operation: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    for status, response in operation.get("responses", {}).items():
        if status.startswith("2"):
            schema = response.get("content", {}).get("application/json", {}).get("schema")
            return status, schema
    return None, None


def _body(operation: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    body = operation.get("requestBody")
    if not body:
        return None, False
    content = body.get("content", {})
    media = content.get("application/json") or next(iter(content.values()), {})
    return media.get("schema"), bool(body.get("required"))


def breaking_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    old_s, new_s = Schemas(old), Schemas(new)
    changes = []
    for path, old_ops in old.get("paths", {}).items():
        for method in METHODS:
            if method not in old_ops:
                continue
            name = f"{method.upper()} {path}"
            new_op = new.get("paths", {}).get(path, {}).get(method)
            if new_op is None:
                changes.append(f"{name}: was removed")
                continue
            old_op = old_ops[method]
            old_params = {(p["in"], p["name"]): p for p in old_op.get("parameters", [])}
            for param in new_op.get("parameters", []):
                key = (param["in"], param["name"])
                where = f"{name} {param['in']} parameter {param['name']}"
                if key not in old_params:
                    if param.get("required"):
                        changes.append(f"{where}: is new and required")
                    continue
                if param.get("required") and not old_params[key].get("required"):
                    changes.append(f"{where}: is now required")
                changes += compare_request(old_s, new_s, old_params[key].get("schema", {}),
                                           param.get("schema", {}), where)
            old_body, _ = _body(old_op)
            new_body, new_body_required = _body(new_op)
            if new_body is not None:
                if old_body is None:
                    if new_body_required:
                        changes.append(f"{name} body: is new and required")
                else:
                    changes += compare_request(old_s, new_s, old_body, new_body, f"{name} body")
            old_status, old_result = _success(old_op)
            new_status, new_result = _success(new_op)
            if old_status != new_status:
                changes.append(f"{name}: answers {new_status} instead of {old_status}")
            elif old_result is not None and new_result is not None:
                changes += compare_response(old_s, new_s, old_result, new_result,
                                            f"{name} response")
    return changes


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.split("\n\n")[1].strip(), file=sys.stderr)
        return 2
    old, new = (json.loads(Path(name).read_text(encoding="utf-8")) for name in argv)
    changes = breaking_changes(old, new)
    for change in changes:
        print(f"breaking: {change}")
    if not changes:
        print("No breaking changes.")
    return 1 if changes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
