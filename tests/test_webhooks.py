"""Webhooks: managing them, the events they get, and sending them signed."""

import asyncio
import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ragolex.core.config import get_settings
from ragolex.core.errors import WebhookFailed
from ragolex.core.network import is_local_host, is_public_address
from ragolex.persistence.database import create_engine, create_session_factory
from ragolex.persistence.repositories import unit_of_work_factory
from ragolex.services.webhook_dispatcher import WebhookDispatcher, signature
from ragolex.webhooks.http_sender import HTTPWebhookSender

from .test_jobs import enqueue, upload

URL = "https://hooks.example.com/ragolex"


def create(client, project="p1", url=URL, events=("file.uploaded", "job.succeeded"), **body):
    return client.post(f"/api/v1/projects/{project}/webhooks",
                       json={"url": url, "events": list(events), **body})


def deliveries(client, webhook_id, project="p1"):
    return client.get(f"/api/v1/projects/{project}/webhooks/{webhook_id}/deliveries").json()


class RecordingSender:
    """Answers every delivery with ``status``, or fails with ``error``."""

    def __init__(self, status=200, error=None):
        self.status, self.error, self.requests = status, error, []

    async def send(self, url, body, headers):
        self.requests.append((url, json.loads(body), dict(headers), body))
        if self.error:
            raise WebhookFailed(self.error)
        return self.status

    async def aclose(self):
        pass


@pytest.fixture
def dispatch(db):
    """Attempt due deliveries with ``sender``; returns whether each attempt found one."""
    def run(sender, times=1, **options):
        async def work():
            engine = create_engine(db)
            try:
                dispatcher = WebhookDispatcher(
                    unit_of_work_factory(create_session_factory(engine)), sender,
                    clock=lambda: 1_700_000_000, **options)
                return [await dispatcher.deliver_next() for _ in range(times)]
            finally:
                await engine.dispose()
        return asyncio.run(work())
    return run


def test_create_returns_the_secret_once(client):
    response = create(client, events=["job.succeeded", "file.uploaded", "job.succeeded"],
                      description="n8n")

    assert response.status_code == 201
    created = response.json()
    assert created["secret"].startswith("whsec_") and len(created["secret"]) > 40
    assert (created["url"], created["events"], created["description"]) == (
        URL, ["file.uploaded", "job.succeeded"], "n8n")
    listed = client.get("/api/v1/projects/p1/webhooks").json()
    assert listed["total"] == 1 and "secret" not in listed["items"][0]
    assert client.get(f"/api/v1/projects/p1/webhooks/{created['id']}").json() == {
        k: v for k, v in created.items() if k != "secret"}


def test_creating_a_webhook_creates_the_project(client):
    create(client, project="fresh")

    assert client.get("/api/v1/projects/fresh").status_code == 200


@pytest.mark.parametrize("body", [
    {"url": "ftp://example.com/x", "events": ["file.uploaded"]},
    {"url": "not a url", "events": ["file.uploaded"]},
    {"url": URL, "events": []},
    {"url": URL, "events": ["file.renamed"]},
    {"url": URL + "/" + "x" * 2000, "events": ["file.uploaded"]},
])
def test_invalid_webhooks_are_rejected(client, body):
    assert client.post("/api/v1/projects/p1/webhooks", json=body).status_code == 422


@pytest.mark.parametrize("url", [
    "http://localhost:5678/webhook", "http://127.0.0.1/x", "http://10.1.2.3/x",
    "http://169.254.169.254/latest/meta-data", "http://[::1]:8000/x", "http://app.localhost/x",
])
def test_webhooks_to_this_network_need_permission(client, monkeypatch, url):
    response = create(client, url=url)

    assert (response.status_code, response.json()) == (422, {"signal": "webhook_url_not_allowed"})
    monkeypatch.setenv("WEBHOOK_ALLOW_PRIVATE_URLS", "true")
    get_settings.cache_clear()
    assert create(client, url=url).status_code == 201


def test_delete_a_webhook(client):
    webhook_id = create(client).json()["id"]

    assert client.delete(f"/api/v1/projects/p1/webhooks/{webhook_id}").status_code == 204
    response = client.delete(f"/api/v1/projects/p1/webhooks/{webhook_id}")
    assert (response.status_code, response.json()) == (404, {"signal": "webhook_not_found"})


def test_another_projects_webhook_is_not_found(client):
    webhook_id = create(client, project="p1").json()["id"]
    create(client, project="p2")

    assert client.get(f"/api/v1/projects/p2/webhooks/{webhook_id}").status_code == 404
    assert client.get("/api/v1/projects/nope/webhooks").json() == {"signal": "project_not_found"}


def test_events_are_queued_for_the_webhooks_that_want_them(client):
    uploads = create(client, events=["file.uploaded"]).json()["id"]
    deletions = create(client, events=["file.deleted"]).json()["id"]

    file_id = upload(client)
    upload(client)  # The same content again: nothing new happened.
    client.delete(f"/api/v1/projects/p1/files/{file_id}")

    [uploaded] = deliveries(client, uploads)["items"]
    assert (uploaded["event"], uploaded["status"], uploaded["attempts"]) == (
        "file.uploaded", "pending", 0)
    assert uploaded["payload"] | {"created_at": None} == {
        "event": "file.uploaded", "created_at": None, "project": "p1",
        "data": {"file_id": file_id, "original_name": "notes.txt",
                 "content_type": "text/plain", "size_bytes": 184}}
    [deleted] = deliveries(client, deletions)["items"]
    assert deleted["payload"]["data"] == {"file_id": file_id}


def test_jobs_send_their_outcome_once_it_is_final(client, run_jobs, make_pdf):
    webhook_id = create(client, events=["job.succeeded", "job.failed"]).json()["id"]
    good = enqueue(client, upload(client)).json()["id"]
    scan = client.post("/api/v1/data/upload/p1",
                       files={"file": ("scan.pdf", make_pdf([""]), "application/pdf")})
    bad = enqueue(client, scan.json()["file_id"]).json()["id"]

    run_jobs(times=2)

    sent = {d["payload"]["data"]["job_id"]: d["payload"] for d in deliveries(client, webhook_id)["items"]}
    assert sent[good]["event"] == "job.succeeded"
    assert sent[good]["data"] | {"file_id": None} == {
        "job_id": good, "file_id": None, "status": "succeeded", "chunks_count": 6,
        "error": None, "attempts": 1}
    assert (sent[bad]["event"], sent[bad]["data"]["error"]) == ("job.failed", "file_has_no_text")


def test_a_delivery_is_signed_and_marked_delivered(client, dispatch):
    created = create(client).json()
    upload(client)
    sender = RecordingSender(status=204)

    assert dispatch(sender, times=2) == [True, False]

    [(url, body, headers, raw)] = sender.requests
    [delivery] = deliveries(client, created["id"])["items"]
    assert url == URL
    assert body["id"] == delivery["id"] == headers["X-Ragolex-Delivery"]
    assert (body["event"], headers["X-Ragolex-Event"]) == ("file.uploaded", "file.uploaded")
    assert headers["Content-Type"] == "application/json"
    expected = hmac.new(created["secret"].encode(), b"1700000000." + raw, hashlib.sha256)
    assert headers["X-Ragolex-Signature"] == f"t=1700000000,v1={expected.hexdigest()}"
    assert (delivery["status"], delivery["attempts"], delivery["response_status"]) == (
        "delivered", 1, 204)
    assert delivery["delivered_at"] is not None and delivery["next_attempt_at"] is None


def test_a_refused_delivery_is_tried_again_later(client, dispatch):
    webhook_id = create(client).json()["id"]
    upload(client)

    dispatch(RecordingSender(status=500), retry_delays=(3600,))

    [delivery] = deliveries(client, webhook_id)["items"]
    assert (delivery["status"], delivery["attempts"], delivery["response_status"],
            delivery["error"]) == ("pending", 1, 500, "HTTP 500")
    assert delivery["next_attempt_at"] is not None
    assert dispatch(RecordingSender()) == [False]  # Not due for an hour.


def test_a_delivery_fails_after_its_last_attempt(client, dispatch):
    webhook_id = create(client).json()["id"]
    upload(client)

    attempts = dispatch(RecordingSender(error="timed out"), times=3, retry_delays=(0,))

    assert attempts == [True, True, False]
    [delivery] = deliveries(client, webhook_id)["items"]
    assert (delivery["status"], delivery["attempts"], delivery["response_status"],
            delivery["error"]) == ("failed", 2, None, "timed out")


def test_a_claimed_delivery_waits_for_its_lease(client, dispatch, db):
    create(client)
    upload(client)

    async def claim():
        engine = create_engine(db)
        try:
            async with unit_of_work_factory(create_session_factory(engine))() as uow:
                claimed = await uow.webhooks.claim_delivery(3600)
                await uow.commit()
                return claimed
        finally:
            await engine.dispose()

    assert asyncio.run(claim()) is not None
    assert dispatch(RecordingSender()) == [False]


def test_ping_sends_to_one_webhook(client, dispatch):
    webhook_id = create(client, events=["job.failed"]).json()["id"]

    response = client.post(f"/api/v1/projects/p1/webhooks/{webhook_id}/ping")
    sender = RecordingSender()
    dispatch(sender)

    assert (response.status_code, response.json()["event"]) == (202, "ping")
    assert sender.requests[0][1]["data"] == {"webhook_id": webhook_id}


def test_deleting_a_project_deletes_its_webhooks(client, query):
    create(client)
    upload(client)

    client.delete("/api/v1/projects/p1")

    assert query("SELECT count(*) FROM webhooks") == [(0,)]
    assert query("SELECT count(*) FROM webhook_deliveries") == [(0,)]


def test_signature_helper():
    assert signature("whsec_x", 1, b"{}") == "t=1,v1=" + hmac.new(
        b"whsec_x", b"1.{}", hashlib.sha256).hexdigest()


@pytest.mark.parametrize(("address", "public"), [
    ("8.8.8.8", True), ("2606:4700:4700::1111", True),
    ("127.0.0.1", False), ("10.0.0.1", False), ("172.16.5.4", False), ("192.168.1.1", False),
    ("169.254.169.254", False), ("100.64.0.1", False), ("0.0.0.0", False), ("::1", False),
    ("fd00::1", False), ("fe80::1%eth0", False), ("::ffff:127.0.0.1", False),
    ("224.0.0.1", False),
])
def test_public_addresses(address, public):
    assert is_public_address(address) is public


@pytest.mark.parametrize(("host", "local"), [
    ("localhost", True), ("LOCALHOST.", True), ("x.localhost", True), ("127.0.0.1", True),
    ("[::1]", True), ("example.com", False), ("8.8.8.8", False),
])
def test_local_hosts(host, local):
    assert is_local_host(host) is local


class _Receiver(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Receiver.received.append((self.path, self.headers["X-Test"], body))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
        else:
            self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def receiver():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Receiver.received = []
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def send(url, allow_private, **options):
    async def go():
        sender = HTTPWebhookSender(allow_private=allow_private, **options)
        try:
            return await sender.send(url, b'{"a":1}', {"X-Test": "yes"})
        finally:
            await sender.aclose()
    return asyncio.run(go())


def test_the_http_sender_posts_the_body(receiver):
    assert send(receiver + "/hook", allow_private=True) == 200
    assert _Receiver.received == [("/hook", "yes", b'{"a":1}')]


def test_the_http_sender_does_not_follow_redirects(receiver):
    assert send(receiver + "/redirect", allow_private=True) == 302
    assert len(_Receiver.received) == 1


def test_the_http_sender_refuses_private_addresses(receiver):
    with pytest.raises(WebhookFailed, match="127.0.0.1 is not a public address"):
        send(receiver + "/hook", allow_private=False)
    assert _Receiver.received == []


def test_the_http_sender_reports_unreachable_receivers():
    with pytest.raises(WebhookFailed, match="could not connect"):
        send("http://127.0.0.1:1/hook", allow_private=True)
    with pytest.raises(WebhookFailed, match="could not be resolved"):
        send("http://no-such-host.invalid/hook", allow_private=False)
