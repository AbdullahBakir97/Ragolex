"""Monthly budgets per tenant, their alerts, and the cost history for dashboards."""

from datetime import UTC, datetime, timedelta

import pytest

from ragolex import cli
from ragolex.core.config import get_settings

from .test_ask_api import upload_process_and_index
from .test_auth import bearer, make_key

ASK = {"question": "Where is the embedding vector stored?", "min_score": 0.2}


@pytest.fixture
def priced(monkeypatch):
    """Prices that make each of the fake model's answers cost $1.20 (1,200 input tokens)."""
    monkeypatch.setenv("LLM_INPUT_PRICE_PER_MILLION", "1000")
    monkeypatch.setenv("LLM_OUTPUT_PRICE_PER_MILLION", "0")
    get_settings.cache_clear()


@pytest.fixture
def budget(monkeypatch, priced):
    def set_(usd):
        monkeypatch.setenv("BUDGET_USD_PER_MONTH", str(usd))
        get_settings.cache_clear()
    return set_


def webhook(client, project, events=("budget.alert",)):
    response = client.post(f"/api/v1/projects/{project}/webhooks",
                           json={"url": "https://hooks.example.com/budget",
                                 "events": list(events)})
    assert response.status_code == 201
    return response.json()["id"]


def sent(client, project, webhook_id):
    items = client.get(f"/api/v1/projects/{project}/webhooks/{webhook_id}/deliveries"
                       ).json()["items"]
    return sorted((item["payload"] for item in items),
                  key=lambda payload: payload["data"]["threshold_percent"])


def test_answers_stop_when_the_budget_is_spent(client, embedder, llm, budget):
    budget(2.5)
    upload_process_and_index(client)

    answers = [client.post("/api/v1/ask/demo", json=ASK) for _ in range(3)]
    refused = client.post("/api/v1/ask/demo", json=ASK)
    streamed = client.post("/api/v1/ask/demo/stream", json=ASK)

    # $1.20, $2.40 and $3.60: the third answer started under the budget.
    assert [answer.status_code for answer in answers] == [200, 200, 200]
    assert (refused.status_code, refused.json()["signal"]) == (429, "budget_exceeded")
    assert streamed.status_code == 429
    assert len(llm.calls) == 3
    # Search still works: only answers cost money.
    assert client.post("/api/v1/search/demo", json={"query": "embedding"}).status_code == 200
    usage = client.get("/api/v1/usage").json()
    assert (usage["budget_usd"], usage["cost_usd"]) == (2.5, pytest.approx(3.6))


def test_reaching_80_and_100_percent_alerts_once_each(client, embedder, llm, budget):
    budget(2.5)
    upload_process_and_index(client)
    # Budget alerts go to the tenant's webhooks that want them, in any project.
    here, elsewhere = webhook(client, "demo"), webhook(client, "other")
    uploads = webhook(client, "demo", events=("file.uploaded",))

    for _ in range(3):
        assert client.post("/api/v1/ask/demo", json=ASK).status_code == 200

    alerts = sent(client, "demo", here)
    assert [alert["data"]["threshold_percent"] for alert in alerts] == [80, 100]
    assert sent(client, "other", elsewhere) == alerts
    eighty, hundred = alerts
    assert eighty["event"] == "budget.alert"
    assert eighty["project"] == "demo"
    assert eighty["data"]["budget_usd"] == 2.5
    assert eighty["data"]["cost_usd"] == pytest.approx(2.4)
    assert hundred["data"]["cost_usd"] == pytest.approx(3.6)
    assert datetime.fromisoformat(eighty["data"]["period_start"]).day == 1
    assert sent(client, "demo", uploads) == []
    logged = client.get("/api/v1/audit", params={"action": "budget.alert"}).json()["items"]
    assert sorted(event["details"]["threshold_percent"] for event in logged) == [80, 100]


def test_without_a_budget_nothing_is_limited_or_announced(client, embedder, llm, priced):
    upload_process_and_index(client)
    alerts = webhook(client, "demo")

    for _ in range(3):
        assert client.post("/api/v1/ask/demo", json=ASK).status_code == 200

    assert client.get("/api/v1/usage").json()["budget_usd"] is None
    assert sent(client, "demo", alerts) == []


def test_a_tenant_can_be_given_its_own_budget(client, embedder, llm, budget, capsys):
    budget(100)
    upload_process_and_index(client)

    assert cli.main(["tenants", "limits", "default", "--budget-usd", "1.50"]) == 0
    assert "budget $1.50/month" in capsys.readouterr().out
    assert client.get("/api/v1/usage").json()["budget_usd"] == 1.5
    # $1.20, then $2.40: over the budget.
    assert [client.post("/api/v1/ask/demo", json=ASK).status_code for _ in range(3)] == [
        200, 200, 429]

    assert cli.main(["tenants", "limits", "default", "--budget-usd", "0"]) == 0
    assert "budget unlimited" in capsys.readouterr().out
    assert client.post("/api/v1/ask/demo", json=ASK).status_code == 200
    assert cli.main(["tenants", "limits", "default", "--budget-usd", "default"]) == 0
    assert client.get("/api/v1/usage").json()["budget_usd"] == 100


@pytest.mark.parametrize("amount", ["-1", "ten", "1.234", "1e3"])
def test_budgets_are_amounts_of_dollars(amount, capsys):
    with pytest.raises(SystemExit):
        cli.main(["tenants", "limits", "default", "--budget-usd", amount])
    assert "use an amount" in capsys.readouterr().err


def test_the_cost_history_counts_each_day_project_and_model(client, embedder, llm, priced):
    upload_process_and_index(client)
    upload_process_and_index(client, project="other")
    for project in ("demo", "demo", "other"):
        assert client.post(f"/api/v1/ask/{project}", json=ASK).status_code == 200
    # No source matches: no model is called, and the answer costs nothing.
    assert client.post("/api/v1/ask/demo", json={
        "question": "Who won the match?", "min_score": 0.99}).status_code == 200

    history = client.get("/api/v1/usage/history", params={"days": 7}).json()

    today = datetime.now(UTC).date()
    assert [day["day"] for day in history["days"]] == [
        (today - timedelta(days=back)).isoformat() for back in range(6, -1, -1)]
    assert history["start"].startswith((today - timedelta(days=6)).isoformat())
    *before, last = history["days"]
    assert all(day["answers"] == 0 and day["cost_usd"] == 0 for day in before)
    assert last == {"day": today.isoformat(), "answers": 4, "input_tokens": 3600,
                    "output_tokens": 120, "cost_usd": pytest.approx(3.6)}
    assert [(p["project"], p["answers"], p["cost_usd"]) for p in history["projects"]] == [
        ("demo", 3, pytest.approx(2.4)), ("other", 1, pytest.approx(1.2))]
    assert [(m["model"], m["answers"]) for m in history["models"]] == [
        ("fake-llm", 3), (None, 1)]


def test_the_history_is_the_tenants_own(client, db, embedder, llm, priced, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    acme, globex = make_key(db, "acme"), make_key(db, "globex")
    client.headers.update(bearer(acme))
    upload_process_and_index(client)
    assert client.post("/api/v1/ask/demo", json=ASK).status_code == 200

    mine = client.get("/api/v1/usage/history", headers=bearer(acme)).json()
    theirs = client.get("/api/v1/usage/history", headers=bearer(globex)).json()

    assert len(mine["days"]) == 30
    assert [p["project"] for p in mine["projects"]] == ["demo"]
    assert theirs["projects"] == theirs["models"] == []
    assert sum(day["answers"] for day in theirs["days"]) == 0


@pytest.mark.parametrize("days", [0, 367])
def test_the_history_covers_one_day_to_a_year(client, days):
    assert client.get("/api/v1/usage/history", params={"days": days}).status_code == 422
