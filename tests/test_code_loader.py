"""Source code is split where its definitions start, each named as its section."""

import pytest

from mini_rag.loaders import code_loader
from mini_rag.loaders.code_loader import CodeLoader

from .test_projects_api import process, upload


def sections(tmp_path, name, language, text):
    path = tmp_path / name
    path.write_text(text)
    documents = CodeLoader(language).load(path, source=name)
    assert all(d.metadata["source"] == name and d.metadata["language"] == language
               for d in documents)
    return [(d.metadata.get("section"), d.text.splitlines()[0]) for d in documents]


@pytest.fixture
def split_classes(monkeypatch):
    """Classes in these samples are short: split them anyway."""
    monkeypatch.setattr(code_loader, "WHOLE_CLASS_CHARACTERS", 40)


PYTHON = '''\
"""Reading files."""
import os

LIMIT = 3


# Reads a file.
@cached
def read(path):
    return open(path).read()


class Reader:
    """Reads."""

    encoding = "utf-8"

    async def read(self, path):
        return path

    def close(self):
        pass
'''


def test_python_is_split_into_definitions_with_their_comments_and_decorators(tmp_path):
    documents = CodeLoader("python").load(_write(tmp_path, "io.py", PYTHON), source="io.py")

    assert [(d.metadata.get("section"), d.text) for d in documents] == [
        (None, '"""Reading files."""\nimport os\n\nLIMIT = 3'),
        ("read", "# Reads a file.\n@cached\ndef read(path):\n    return open(path).read()"),
        ("Reader", PYTHON[PYTHON.index("class Reader"):].rstrip()),
    ]


def test_long_classes_are_split_into_members(tmp_path, split_classes):
    assert sections(tmp_path, "io.py", "python", PYTHON)[2:] == [
        ("Reader", "class Reader:"),
        # Methods are dedented, so each reads as code of its own.
        ("Reader.read", "async def read(self, path):"),
        ("Reader.close", "def close(self):"),
    ]


def test_a_class_keeps_its_docstring_and_attributes(tmp_path, split_classes):
    path = _write(tmp_path, "io.py", PYTHON)
    [header] = [d for d in CodeLoader("python").load(path, "io.py")
                if d.metadata.get("section") == "Reader"]

    assert header.text == 'class Reader:\n    """Reads."""\n\n    encoding = "utf-8"'


@pytest.mark.parametrize(("name", "language", "text", "expected"), [
    ("lib.rs", "rust", '''\
use std::fmt;

/// A point.
#[derive(Debug)]
pub struct Point {
    x: i32,
}

impl<'a> fmt::Display for Point {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let brace = '{';
        write!(f, "({})", self.x)
    }
}

pub fn longest<'a>(x: &'a str, y: &'a str) -> &'a str {
    if x.len() > y.len() { x } else { y }
}
''', [(None, "use std::fmt;"), ("Point", "/// A point."), ("Point", "impl<'a> fmt::Display for Point {"),
      ("Point.fmt", "fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {"),
      ("longest", "pub fn longest<'a>(x: &'a str, y: &'a str) -> &'a str {")]),
    ("store.ts", "typescript", '''\
import { ref } from "vue";

export const LIMIT = 3;

/** Adds. */
export function add(a: number, b: number): number {
  return a + b;
}

export const double = (n: number) => {
  return n * 2;
};

export class Store {
  private items: string[] = [];

  @Watch("x")
  add(item: string): void {
    this.items.push(`item ${item} {`);
  }
}
''', [(None, 'import { ref } from "vue";'), ("add", "/** Adds. */"),
      ("double", "export const double = (n: number) => {"), ("Store", "export class Store {"),
      ("Store.add", '@Watch("x")')]),
    ("Service.java", "java", '''\
package demo;

public class Service {
    private final String name;

    public Service(String name) {
        this.name = name;
    }

    @Override
    public String toString() {
        return "Service{" + name + "}";
    }
}
''', [(None, "package demo;"), ("Service", "public class Service {"),
      ("Service.Service", "public Service(String name) {"), ("Service.toString", "@Override")]),
    ("server.go", "go", '''\
package main

// Server serves.
type Server struct {
	addr string
}

func (s *Server) Start() error {
	fmt.Println(`a raw {
string`)
	return nil
}
''', [(None, "package main"), ("Server", "// Server serves."),
      ("Server.Start", "func (s *Server) Start() error {")]),
    ("shape.cpp", "cpp", '''\
#include <vector>

namespace geo {

template <typename T>
T clamp(T v, T lo, T hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

}  // namespace geo

Point::Point(int x)
    : x_(x) {
}
''', [(None, "#include <vector>"), ("geo", "namespace geo {"), ("geo.clamp", "template <typename T>"),
      ("Point::Point", "Point::Point(int x)")]),
    ("count.c", "c", '''\
#include <stdio.h>

/* Adds one. */
int increment(int *value)
{
    char c = '}';
    return ++*value;
}
''', [(None, "#include <stdio.h>"), ("increment", "/* Adds one. */")]),
    ("Greeter.cs", "csharp", '''\
namespace Demo
{
    public class Greeter
    {
        [Obsolete]
        public string Greet(string name)
        {
            return $"Hello {name}";
        }
    }
}
''', [("Demo", "namespace Demo"), ("Demo.Greeter", "public class Greeter"),
      ("Demo.Greeter.Greet", "[Obsolete]")]),
    ("Repo.kt", "kotlin", '''\
data class User(val name: String)

class Repo {
    suspend fun load(id: Int): User {
        return User("x")
    }
}
''', [(None, "data class User(val name: String)"), ("Repo", "class Repo {"),
      ("Repo.load", "suspend fun load(id: Int): User {")]),
    ("Cart.php", "php", '''\
<?php

class Cart
{
    public function total(): int
    {
        return 0; // it's {
    }
}
''', [(None, "<?php"), ("Cart", "class Cart"), ("Cart.total", "public function total(): int")]),
    ("Point.swift", "swift", '''\
extension Point {
    mutating func move(by dx: Int) {
        x += dx
    }
}
''', [("Point", "extension Point {"), ("Point.move", "mutating func move(by dx: Int) {")]),
])
def test_languages_with_brackets_are_split_into_definitions(tmp_path, split_classes, name,
                                                            language, text, expected):
    assert sections(tmp_path, name, language, text) == expected


def test_calls_and_one_line_statements_are_no_definitions(tmp_path):
    text = '''\
const LIMIT = 3;
export default defineConfig({
  plugins: [],
});
describe("store", () => {
  it("adds", () => {});
});
'''
    assert sections(tmp_path, "a.test.js", "javascript", text) == [(None, "const LIMIT = 3;")]


@pytest.mark.parametrize(("name", "language", "text"), [
    ("broken.py", "python", "def broken(:\n    pass\n"),
    # A regular expression's bracket cannot be told from code by following brackets.
    ("regex.js", "javascript", "function f(x) {\n  return /[{]/.test(x);\n}\n"),
])
def test_a_file_that_cannot_be_followed_is_one_document(tmp_path, name, language, text):
    path = _write(tmp_path, name, text)

    [document] = CodeLoader(language).load(path, source=name)

    assert document.text == text
    assert document.metadata == {"source": name, "language": language}


def test_an_empty_file_has_no_documents(tmp_path):
    assert CodeLoader("go").load(_write(tmp_path, "empty.go", "\n\n"), source="empty.go") == []


def test_uploaded_code_is_chunked_by_definition(client):
    file_id = upload(client, "demo", name="io.py", content=PYTHON.encode(),
                     content_type="text/plain")
    process(client, "demo", file_id, chunk_size=1000, overlap_size=0)

    files = client.get("/api/v1/projects/demo/files").json()["items"]
    chunks = client.get(f"/api/v1/projects/demo/files/{file_id}/chunks").json()["items"]

    assert files[0]["content_type"] == "text/x-python"
    assert [c["metadata"].get("section") for c in chunks] == [None, "read", "Reader"]
    assert chunks[1]["text"].startswith("# Reads a file.\n@cached\ndef read(path):")
    assert chunks[1]["metadata"]["language"] == "python"


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path
