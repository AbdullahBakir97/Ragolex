"""The SQL repositories and the test fakes must match the domain interfaces.

Otherwise service tests could pass against a fake that no longer behaves
like (or even looks like) the real implementation.
"""

import inspect

import pytest

from ragolex.domain import repositories as interfaces
from ragolex.persistence import repositories as sql

from . import fakes

CONTRACTS = [
    (interfaces.ProjectRepository, sql.SqlProjectRepository, fakes.FakeProjects),
    (interfaces.FileRepository, sql.SqlFileRepository, fakes.FakeFiles),
    (interfaces.ChunkRepository, sql.SqlChunkRepository, fakes.FakeChunks),
    (interfaces.AnswerRepository, sql.SqlAnswerRepository, fakes.FakeAnswers),
    (interfaces.ConversationRepository, sql.SqlConversationRepository, fakes.FakeConversations),
    (interfaces.JobRepository, sql.SqlJobRepository, fakes.FakeJobs),
    (interfaces.WebhookRepository, sql.SqlWebhookRepository, fakes.FakeWebhooks),
    (interfaces.WidgetRepository, sql.SqlWidgetRepository, fakes.FakeWidgets),
    (interfaces.AuditRepository, sql.SqlAuditRepository, fakes.FakeAudit),
    (interfaces.SourceRepository, sql.SqlSourceRepository, fakes.FakeSources),
    (interfaces.TenantRepository, sql.SqlTenantRepository, fakes.FakeTenants),
    (interfaces.ApiKeyRepository, sql.SqlApiKeyRepository, fakes.FakeApiKeys),
    (interfaces.UsageRepository, sql.SqlUsageRepository, fakes.FakeUsage),
    (interfaces.UnitOfWork, sql.SqlUnitOfWork, fakes.FakeUnitOfWork),
]


def public_methods(cls):
    return {name: member for name, member in inspect.getmembers(cls, inspect.isfunction)
            if not name.startswith("_")}


def parameters(function):
    return [(p.name, p.kind) for p in inspect.signature(function).parameters.values()]


@pytest.mark.parametrize(("interface", "implementation"),
                         [(i, impl) for i, *impls in CONTRACTS for impl in impls])
def test_implementation_matches_interface(interface, implementation):
    expected = public_methods(interface)
    actual = public_methods(implementation)

    for name, method in expected.items():
        assert name in actual, f"{implementation.__name__} lacks {name}"
        assert inspect.iscoroutinefunction(actual[name]), f"{implementation.__name__}.{name} must be async"
        assert parameters(actual[name]) == parameters(method), f"{implementation.__name__}.{name} signature differs"


@pytest.mark.parametrize("implementation", [sql.SqlUnitOfWork, fakes.FakeUnitOfWork])
def test_unit_of_work_exposes_the_repositories(implementation):
    assert set(interfaces.UnitOfWork.__annotations__) == {"projects", "files", "chunks", "answers",
                                                            "conversations", "jobs", "webhooks",
                                                            "widgets", "audit", "sources", "tenants", "api_keys", "usage"}
    instance = implementation(None) if implementation is sql.SqlUnitOfWork else implementation()

    assert all(hasattr(instance, name) for name in interfaces.UnitOfWork.__annotations__)
