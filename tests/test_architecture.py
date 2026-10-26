"""Enforce the layer rules described in the README's Architecture section."""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "ragolex"

# Which ragolex layers each layer may import. Web frameworks are only
# allowed in the API layer, so everything below it works without HTTP, and
# only persistence (and the API, which wires it up) may use SQLAlchemy.
# Only embeddings, llm and ocr may use a model provider's SDK.
ALLOWED_LAYERS = {
    "api": {"api", "core", "domain", "services", "storage", "loaders", "text", "persistence",
            "embeddings", "llm", "rerankers", "webhooks", "scanners", "connectors", "ocr"},
    # Services use the repository interfaces in domain, never persistence.
    "services": {"core", "domain", "storage", "loaders", "text", "prompts", "evaluation"},
    "persistence": {"core", "domain"},
    "storage": {"core", "domain"},
    "loaders": {"core", "domain"},
    # Services use the Embedder and LLM interfaces in domain, never a provider SDK.
    "embeddings": {"core", "domain"},
    "llm": {"core", "domain"},
    "rerankers": {"core", "domain"},
    "ocr": {"core", "domain"},
    # Sends webhook deliveries over HTTP; services use the WebhookSender interface.
    "webhooks": {"core", "domain"},
    # Scans uploads for malware; services use the MalwareScanner interface.
    "scanners": {"core", "domain"},
    # Fetch documents from elsewhere (websites); services use the Crawler interface.
    "connectors": {"core", "domain"},
    "text": set(),
    "prompts": {"domain"},
    # Datasets and metrics; services run them, the CLI wires them up.
    "evaluation": {"domain"},
    "core": {"domain"},
    "domain": set(),
}
WEB_FRAMEWORKS = {"fastapi", "starlette"}
DATABASE_LIBRARIES = {"sqlalchemy", "asyncpg", "alembic", "pgvector"}
PROVIDER_SDKS = {"openai"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_every_layer_is_covered():
    layers = {path.name for path in PACKAGE.iterdir() if (path / "__init__.py").exists()}

    assert layers == set(ALLOWED_LAYERS)


@pytest.mark.parametrize("layer", sorted(ALLOWED_LAYERS))
def test_layer_imports_follow_the_rules(layer):
    violations = []
    for path in sorted((PACKAGE / layer).rglob("*.py")):
        for module in imported_modules(path):
            top, _, rest = module.partition(".")
            if top in WEB_FRAMEWORKS and layer != "api":
                violations.append(f"{path.name} imports {module}")
            if top in DATABASE_LIBRARIES and layer not in {"persistence", "api"}:
                violations.append(f"{path.name} imports {module}")
            if top in PROVIDER_SDKS and layer not in {"embeddings", "llm", "ocr"}:
                violations.append(f"{path.name} imports {module}")
            if top == "ragolex":
                target = rest.partition(".")[0]
                if target != layer and target not in ALLOWED_LAYERS[layer]:
                    violations.append(f"{path.name} imports {module}")

    assert violations == []
