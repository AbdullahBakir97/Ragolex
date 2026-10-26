import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError

from ragolex.domain.models import AnswerRecord, Chunk, UsageTotals
from ragolex.persistence.database import create_engine, create_session_factory
from ragolex.persistence.repositories import SqlTenantRepository, SqlUnitOfWork
from ragolex.persistence.tables import EMBEDDING_DIMENSIONS, ProjectRow

pytestmark = pytest.mark.anyio


@pytest.fixture
async def session_factory(db):
    engine = create_engine(db)
    yield create_session_factory(engine)
    await engine.dispose()


async def tenant_uow(session, tenant="default"):
    """A unit of work acting for ``tenant``, created if needed."""
    found = await SqlTenantRepository(session).get_or_create(tenant)
    return SqlUnitOfWork(session, found.id)


@pytest.fixture
async def uow(session_factory):
    async with session_factory() as session:
        yield await tenant_uow(session)


async def add_file(uow, project, key="abc_notes.txt", size=10):
    return await uow.files.add(project_id=project.id, key=key, original_name="notes.txt",
                               content_type="text/plain", size_bytes=size)


def vector(*head: float) -> list[float]:
    """A full-length embedding that starts with ``head`` and is zero after it."""
    return [*head, *[0.0] * (EMBEDDING_DIMENSIONS - len(head))]


async def embed_all(uow, project, vectors_by_text: dict[str, list[float]]):
    pending = await uow.chunks.list_unembedded(project.id, file_id=None, limit=100)
    await uow.chunks.set_embeddings(
        {chunk.id: vectors_by_text[chunk.text] for chunk in pending if chunk.text in vectors_by_text})


async def test_get_or_create_project_is_idempotent(uow):
    first = await uow.projects.get_or_create("demo")
    second = await uow.projects.get_or_create("demo")

    assert first == second
    assert first.name == "demo" and first.created_at is not None
    assert await uow.projects.get_by_name("other") is None


async def test_projects_are_listed_by_name(uow):
    for name in ("notes", "demo", "papers"):
        await uow.projects.get_or_create(name)

    assert [p.name for p in await uow.projects.list_all(offset=0, limit=10)] == ["demo", "notes", "papers"]
    assert [p.name for p in await uow.projects.list_all(offset=1, limit=1)] == ["notes"]
    assert await uow.projects.count() == 3


async def test_add_and_get_file(uow):
    project = await uow.projects.get_or_create("demo")

    added = await add_file(uow, project, size=1234)

    assert added.id > 0 and added.size_bytes == 1234 and added.created_at is not None
    assert await uow.files.get_by_key(project.id, "abc_notes.txt") == added
    assert await uow.files.get_by_key(project.id, "missing.txt") is None


async def test_file_keys_are_unique_per_project(uow):
    first = await uow.projects.get_or_create("a")
    second = await uow.projects.get_or_create("b")
    await add_file(uow, first)
    await add_file(uow, second)  # same key, other project: fine

    with pytest.raises(IntegrityError):
        await add_file(uow, first)


async def test_files_are_listed_in_upload_order_with_paging(uow):
    project = await uow.projects.get_or_create("demo")
    keys = [f"k{i}_f.txt" for i in range(5)]
    for key in keys:
        await add_file(uow, project, key=key)

    page = await uow.files.list_for_project(project.id, offset=1, limit=2)

    assert [f.key for f in page] == keys[1:3]
    assert await uow.files.count_for_project(project.id) == 5


async def test_files_keep_their_tags_and_can_be_listed_by_tag(uow):
    project = await uow.projects.get_or_create("demo")
    other = await uow.projects.get_or_create("other")
    tagged = await uow.files.add(project_id=project.id, key="a_guide.txt", original_name="guide.txt",
                                 content_type="text/plain", size_bytes=1, tags=["guides", "v2"])
    assert tagged.tags == ("guides", "v2")
    await add_file(uow, project, key="b_notes.txt")
    await uow.files.add(project_id=other.id, key="c_x.txt", original_name="x.txt",
                        content_type="text/plain", size_bytes=1, tags=["guides"])

    untagged = await add_file(uow, project, key="d_more.txt")
    assert untagged.tags == ()
    updated = await uow.files.set_tags(project.id, "d_more.txt", ["guides"])
    assert updated.tags == ("guides",)
    assert await uow.files.set_tags(project.id, "missing.txt", ["x"]) is None

    listed = await uow.files.list_for_project(project.id, offset=0, limit=10, tag="guides")
    assert [f.key for f in listed] == ["a_guide.txt", "d_more.txt"]
    assert await uow.files.count_for_project(project.id, tag="guides") == 2
    assert await uow.files.count_for_project(project.id, tag="v3") == 0
    assert await uow.files.count_for_project(project.id) == 3
    assert [(t.tag, t.files) for t in await uow.files.tag_counts(project.id)] == [
        ("guides", 2), ("v2", 1)]
    assert await uow.files.tag_counts(other.id) != await uow.files.tag_counts(project.id)


async def test_replace_chunks_for_file(uow):
    project = await uow.projects.get_or_create("demo")
    file = await add_file(uow, project)
    await uow.chunks.replace_for_file(file, [Chunk(i, f"old {i}") for i in range(3)])

    new = [Chunk(0, "new 0", {"page": 1}), Chunk(1, "new 1", {"page": 2})]
    await uow.chunks.replace_for_file(file, new)

    assert await uow.chunks.list_for_file(file.id, offset=0, limit=10) == new
    assert await uow.chunks.count_for_file(file.id) == 2
    assert await uow.chunks.count_for_project(project.id) == 2


async def test_chunks_are_listed_by_index_with_paging(uow):
    project = await uow.projects.get_or_create("demo")
    file = await add_file(uow, project)
    await uow.chunks.replace_for_file(file, [Chunk(i, f"c{i}") for i in reversed(range(5))])

    page = await uow.chunks.list_for_file(file.id, offset=2, limit=2)

    assert [c.index for c in page] == [2, 3]


async def test_deleting_a_project_cascades_to_files_and_chunks(uow):
    project = await uow.projects.get_or_create("demo")
    file = await add_file(uow, project)
    await uow.chunks.replace_for_file(file, [Chunk(0, "text")])

    assert await uow.projects.delete("demo") is True

    assert await uow.projects.get_by_name("demo") is None
    assert await uow.files.count_for_project(project.id) == 0
    assert await uow.chunks.count_for_file(file.id) == 0
    assert await uow.projects.delete("demo") is False


async def test_uncommitted_work_is_discarded_and_commit_persists(session_factory):
    async with session_factory() as session:
        await (await tenant_uow(session)).projects.get_or_create("discarded")
    async with session_factory() as session:
        uow = await tenant_uow(session)
        await uow.projects.get_or_create("kept")
        await uow.commit()

    async with session_factory() as session:
        uow = await tenant_uow(session)
        assert await uow.projects.get_by_name("discarded") is None
        assert await uow.projects.get_by_name("kept") is not None


async def test_unembedded_chunks_are_listed_oldest_first_until_embedded(uow):
    project = await uow.projects.get_or_create("demo")
    first = await add_file(uow, project, key="a_1.txt")
    second = await add_file(uow, project, key="b_2.txt")
    await uow.chunks.replace_for_file(first, [Chunk(0, "a0"), Chunk(1, "a1")])
    await uow.chunks.replace_for_file(second, [Chunk(0, "b0")])

    pending = await uow.chunks.list_unembedded(project.id, file_id=None, limit=10)
    assert [c.text for c in pending] == ["a0", "a1", "b0"]
    assert [c.text for c in await uow.chunks.list_unembedded(project.id, file_id=second.id, limit=10)] == ["b0"]
    assert len(await uow.chunks.list_unembedded(project.id, file_id=None, limit=2)) == 2

    await uow.chunks.set_embeddings({pending[0].id: vector(1.0), pending[2].id: vector(0.0, 1.0)})

    assert [c.text for c in await uow.chunks.list_unembedded(project.id, file_id=None, limit=10)] == ["a1"]
    assert await uow.chunks.count_embedded_for_project(project.id) == 2


async def test_set_embeddings_skips_chunks_deleted_meanwhile(uow):
    project = await uow.projects.get_or_create("demo")
    file = await add_file(uow, project)
    await uow.chunks.replace_for_file(file, [Chunk(0, "old")])
    [old] = await uow.chunks.list_unembedded(project.id, file_id=None, limit=10)
    await uow.chunks.replace_for_file(file, [Chunk(0, "new")])  # e.g. reprocessed

    await uow.chunks.set_embeddings({old.id: vector(1.0)})

    assert await uow.chunks.count_embedded_for_project(project.id) == 0


async def test_reprocessing_a_file_drops_its_embeddings(uow):
    project = await uow.projects.get_or_create("demo")
    file = await add_file(uow, project)
    await uow.chunks.replace_for_file(file, [Chunk(0, "text")])
    await embed_all(uow, project, {"text": vector(1.0)})

    await uow.chunks.replace_for_file(file, [Chunk(0, "text")])

    assert await uow.chunks.count_embedded_for_project(project.id) == 0


async def test_search_ranks_chunks_by_cosine_similarity(uow):
    project = await uow.projects.get_or_create("demo")
    file = await add_file(uow, project, key="k_doc.pdf")
    await uow.chunks.replace_for_file(file, [
        Chunk(0, "same", {"page": 1}), Chunk(1, "close", {"page": 2}),
        Chunk(2, "opposite"), Chunk(3, "not indexed")])
    await embed_all(uow, project, {
        "same": vector(1.0, 0.0), "close": vector(1.0, 1.0), "opposite": vector(-1.0, 0.0)})

    hits = await uow.chunks.search(project.id, vector(2.0, 0.0), top_k=10, min_score=None)

    assert [hit.chunk.text for hit in hits] == ["same", "close", "opposite"]
    assert [round(hit.score, 4) for hit in hits] == [1.0, 0.7071, -1.0]
    assert hits[0].file_key == "k_doc.pdf"
    assert hits[0].chunk == Chunk(0, "same", {"page": 1})


async def test_search_respects_top_k_and_min_score(uow):
    project = await uow.projects.get_or_create("demo")
    file = await add_file(uow, project)
    await uow.chunks.replace_for_file(file, [Chunk(0, "same"), Chunk(1, "close"), Chunk(2, "far")])
    await embed_all(uow, project, {
        "same": vector(1.0, 0.0), "close": vector(1.0, 1.0), "far": vector(0.0, 1.0)})
    query = vector(1.0, 0.0)

    top_two = await uow.chunks.search(project.id, query, top_k=2, min_score=None)
    above_half = await uow.chunks.search(project.id, query, top_k=10, min_score=0.5)

    assert [hit.chunk.text for hit in top_two] == ["same", "close"]
    assert [hit.chunk.text for hit in above_half] == ["same", "close"]


async def test_search_stays_within_the_project(uow):
    mine = await uow.projects.get_or_create("mine")
    other = await uow.projects.get_or_create("other")
    for project, chunk_text in [(mine, "my text"), (other, "their text")]:
        file = await add_file(uow, project)
        await uow.chunks.replace_for_file(file, [Chunk(0, chunk_text)])
        await embed_all(uow, project, {chunk_text: vector(1.0)})

    hits = await uow.chunks.search(mine.id, vector(1.0), top_k=10, min_score=None)

    assert [hit.chunk.text for hit in hits] == ["my text"]
    assert await uow.chunks.search(other.id + 100, vector(1.0), top_k=10, min_score=None) == []


async def test_search_finds_top_k_even_when_most_neighbours_belong_to_other_projects(uow):
    # Without an iterative index scan, the HNSW index would return its
    # nearest candidates (all from "crowd") and the project filter would
    # leave nothing.
    crowd = await uow.projects.get_or_create("crowd")
    small = await uow.projects.get_or_create("small")
    crowd_file = await add_file(uow, crowd)
    await uow.chunks.replace_for_file(crowd_file, [Chunk(i, f"crowd {i}") for i in range(300)])
    await embed_all(uow, crowd, {f"crowd {i}": vector(1.0, i / 1000) for i in range(300)})
    small_file = await add_file(uow, small)
    await uow.chunks.replace_for_file(small_file, [Chunk(0, "mine 0"), Chunk(1, "mine 1")])
    await embed_all(uow, small, {"mine 0": vector(0.0, 1.0), "mine 1": vector(0.1, 1.0)})
    # Force the HNSW index, as the planner would choose for a large table.
    # The test never commits, so this is rolled back.
    await uow.session.execute(text("DROP INDEX ix_chunks_project_id"))
    await uow.session.execute(text("SET LOCAL enable_seqscan = off"))

    hits = await uow.chunks.search(small.id, vector(1.0, 0.0), top_k=2, min_score=None)

    assert [hit.chunk.text for hit in hits] == ["mine 1", "mine 0"]


def answer_record(project, **overrides):
    values = {"project_id": project.id, "prompt_version": "answer-v1", "model": "m",
              "streamed": False, "answered": True, "input_tokens": 1000, "output_tokens": 50,
              "cost_usd": 0.00048}
    return AnswerRecord(**{**values, **overrides})


async def test_answer_totals_add_up_one_project(uow):
    project = await uow.projects.get_or_create("demo")
    other = await uow.projects.get_or_create("other")
    await uow.answers.add(answer_record(project))
    await uow.answers.add(answer_record(project, streamed=True, input_tokens=500,
                                        output_tokens=20, cost_usd=0.00023))
    # No source matched: the model was not called.
    await uow.answers.add(answer_record(project, model=None, answered=False, input_tokens=0,
                                        output_tokens=0, cost_usd=0))
    # Called, but the provider reported no usage, so the cost is unknown.
    await uow.answers.add(answer_record(project, answered=False, input_tokens=None,
                                        output_tokens=None, cost_usd=None))
    await uow.answers.add(answer_record(other))

    totals = await uow.answers.totals_for_project(project.id)

    assert totals == UsageTotals(answers=4, answered=2, input_tokens=1500, output_tokens=70,
                                 cost_usd=pytest.approx(0.00071), unpriced_answers=1)


async def test_answer_totals_of_a_project_without_answers_are_zero(uow):
    project = await uow.projects.get_or_create("demo")

    assert await uow.answers.totals_for_project(project.id) == UsageTotals(
        answers=0, answered=0, input_tokens=0, output_tokens=0, cost_usd=0, unpriced_answers=0)


async def test_deleting_a_project_deletes_its_answer_records(uow):
    project = await uow.projects.get_or_create("demo")
    await uow.answers.add(answer_record(project))

    await uow.session.execute(delete(ProjectRow).where(ProjectRow.id == project.id))

    assert (await uow.answers.totals_for_project(project.id)).answers == 0


async def test_conversations_keep_their_messages_in_order(uow):
    from ragolex.domain.models import ConversationMessage, StoredCitation

    project = await uow.projects.get_or_create("demo")
    conversation = await uow.conversations.create(project.id, None)
    citation = StoredCitation(number=1, file_key="a_notes.txt", chunk_index=2, page=3, score=0.75,
                              text="Cats purr.")
    await uow.conversations.add_messages(conversation.id, [
        ConversationMessage(role="user", content="Do cats purr?"),
        ConversationMessage(role="assistant", content="Yes [1].", citations=[citation],
                            prompt_version="answer-v1"),
    ], title="Do cats purr?")
    await uow.conversations.add_messages(conversation.id, [
        ConversationMessage(role="user", content="And dogs?"),
        ConversationMessage(role="assistant", content=None, prompt_version="answer-v1",
                            search_question="Do dogs purr?"),
    ])
    await uow.commit()

    stored = await uow.conversations.get(project.id, conversation.id)
    messages = await uow.conversations.messages(conversation.id)
    last_two = await uow.conversations.messages(conversation.id, last=2)

    assert stored.title == "Do cats purr?"  # kept: the second call gave no title
    assert stored.updated_at >= conversation.updated_at
    assert [(m.role, m.content) for m in messages] == [
        ("user", "Do cats purr?"), ("assistant", "Yes [1]."), ("user", "And dogs?"),
        ("assistant", None)]
    assert messages[1].citations == [citation]
    assert messages[3].search_question == "Do dogs purr?"
    assert all(m.created_at is not None for m in messages)
    assert [m.content for m in last_two] == ["And dogs?", None]


async def test_conversations_belong_to_their_project(uow):
    first = await uow.projects.get_or_create("first")
    second = await uow.projects.get_or_create("second")
    mine = await uow.conversations.create(first.id, "Mine")
    await uow.conversations.create(second.id, None)

    assert await uow.conversations.get(second.id, mine.id) is None
    assert await uow.conversations.delete(second.id, mine.id) is False
    assert [c.title for c in await uow.conversations.list_for_project(first.id, offset=0, limit=10)] == ["Mine"]
    assert await uow.conversations.count_for_project(second.id) == 1


async def test_conversations_are_listed_by_last_update(uow, session_factory):
    project = await uow.projects.get_or_create("demo")
    older = await uow.conversations.create(project.id, "Older")
    newer = await uow.conversations.create(project.id, "Newer")
    await uow.commit()
    # now() is the time of the transaction, so the update happens in a later one.
    async with session_factory() as session:
        later = await tenant_uow(session)
        await later.conversations.add_messages(older.id, [])
        await later.commit()

    listed = await uow.conversations.list_for_project(project.id, offset=0, limit=10)

    assert [c.id for c in listed] == [older.id, newer.id]


async def test_deleting_a_conversation_deletes_its_messages(uow):
    from ragolex.domain.models import ConversationMessage

    project = await uow.projects.get_or_create("demo")
    conversation = await uow.conversations.create(project.id, None)
    await uow.conversations.add_messages(conversation.id,
                                         [ConversationMessage(role="user", content="Hi")])

    assert await uow.conversations.delete(project.id, conversation.id) is True
    await uow.commit()
    assert await uow.session.scalar(text("SELECT count(*) FROM conversation_messages")) == 0


async def test_answers_keep_their_feedback_and_are_listed_by_rating(uow):
    from ragolex.domain.models import ConversationMessage, Feedback, FeedbackCounts

    project = await uow.projects.get_or_create("demo")
    other = await uow.projects.get_or_create("other")
    conversation = await uow.conversations.create(project.id, None)
    first = await uow.conversations.add_messages(conversation.id, [
        ConversationMessage(role="user", content="Do cats purr?"),
        ConversationMessage(role="assistant", content="Yes [1]."),
    ])
    second = await uow.conversations.add_messages(conversation.id, [
        ConversationMessage(role="user", content="And dogs?"),
        ConversationMessage(role="assistant", content=None),
    ])
    elsewhere = await uow.conversations.create(other.id, None)
    foreign = await uow.conversations.add_messages(elsewhere.id, [
        ConversationMessage(role="user", content="Hm?"),
        ConversationMessage(role="assistant", content="No."),
    ])
    assert first[0] < first[1] < second[0] < second[1]

    await uow.conversations.set_feedback(first[1], Feedback("up"))
    await uow.commit()
    await uow.conversations.set_feedback(second[1], Feedback("down", "Dogs do not purr."))
    await uow.conversations.set_feedback(foreign[1], Feedback("down"))
    await uow.commit()

    rated = await uow.conversations.rated_answers(project.id, rating=None, offset=0, limit=10)
    assert [(r.message_id, r.question, r.answer, r.feedback.rating, r.feedback.comment)
            for r in rated] == [(second[1], "And dogs?", None, "down", "Dogs do not purr."),
                                (first[1], "Do cats purr?", "Yes [1].", "up", None)]
    down = await uow.conversations.rated_answers(project.id, rating="down", offset=0, limit=10)
    assert [r.message_id for r in down] == [second[1]]
    assert await uow.conversations.count_feedback(project.id) == FeedbackCounts(up=1, down=1)

    await uow.conversations.set_feedback(first[1], None)
    message = await uow.conversations.get_message(conversation.id, first[1])
    assert (message.id, message.feedback) == (first[1], None)
    assert await uow.conversations.get_message(elsewhere.id, first[1]) is None
    assert await uow.conversations.count_feedback(project.id) == FeedbackCounts(up=0, down=1)


async def test_a_rating_must_be_up_or_down(uow):
    from ragolex.domain.models import ConversationMessage, Feedback

    project = await uow.projects.get_or_create("demo")
    conversation = await uow.conversations.create(project.id, None)
    [message_id] = await uow.conversations.add_messages(
        conversation.id, [ConversationMessage(role="assistant", content="Yes.")])

    with pytest.raises(IntegrityError):
        await uow.conversations.set_feedback(message_id, Feedback("sideways"))


async def hybrid_project(uow):
    project = await uow.projects.get_or_create("demo")
    file = await add_file(uow, project, key="k_guide.txt")
    await uow.chunks.replace_for_file(file, [
        Chunk(0, "Deploys run from the main branch."),
        Chunk(1, "Rollbacks restore the previous release."),
        Chunk(2, "Not indexed, and about rollbacks too.")])
    await embed_all(uow, project, {
        "Deploys run from the main branch.": vector(1.0, 0.0),
        "Rollbacks restore the previous release.": vector(0.8, 0.6)})
    return project


async def test_hybrid_search_ranks_chunks_sharing_the_questions_words_higher(uow):
    project = await hybrid_project(uow)

    by_meaning = await uow.chunks.search(project.id, vector(1.0, 0.0), top_k=5, min_score=None)
    hybrid = await uow.chunks.search(project.id, vector(1.0, 0.0), top_k=5, min_score=None,
                                     query="How do I roll back a release?")

    assert [hit.chunk.index for hit in by_meaning] == [0, 1]
    # Second by meaning but first by words ("release"), so first overall.
    assert [hit.chunk.index for hit in hybrid] == [1, 0]
    # Scores stay the cosine similarity, which the minimum score is compared with.
    assert [round(hit.score, 4) for hit in hybrid] == [0.8, 1.0]
    assert hybrid[0].file_key == "k_guide.txt"


async def test_hybrid_search_keeps_the_minimum_score_and_top_k(uow):
    project = await hybrid_project(uow)

    strict = await uow.chunks.search(project.id, vector(1.0, 0.0), top_k=5, min_score=0.9,
                                     query="release")
    one = await uow.chunks.search(project.id, vector(1.0, 0.0), top_k=1, min_score=None,
                                  query="release")

    assert [hit.chunk.index for hit in strict] == [0]
    assert [hit.chunk.index for hit in one] == [1]


async def test_hybrid_search_without_searchable_words_ranks_by_meaning(uow):
    project = await hybrid_project(uow)
    other = await uow.projects.get_or_create("other")

    hits = await uow.chunks.search(project.id, vector(1.0, 0.0), top_k=5, min_score=None,
                                   query="the of and")
    elsewhere = await uow.chunks.search(other.id, vector(1.0, 0.0), top_k=5, min_score=None,
                                        query="release")

    assert [hit.chunk.index for hit in hits] == [0, 1]
    assert elsewhere == []


async def filtered_project(uow):
    project = await uow.projects.get_or_create("demo")
    guide = await add_file(uow, project, key="g_guide.pdf")
    notes = await add_file(uow, project, key="n_notes.txt")
    await uow.chunks.replace_for_file(guide, [
        Chunk(0, "Release notes, page one.", {"page": 1, "lang": "en"}),
        Chunk(1, "Release steps, page two.", {"page": 2, "lang": "en"}),
        Chunk(2, "Release checklist, page three.", {"page": 3, "lang": "de"})])
    await uow.chunks.replace_for_file(notes, [Chunk(0, "Release notes without pages.")])
    await embed_all(uow, project, {
        "Release notes, page one.": vector(1.0, 0.1),
        "Release steps, page two.": vector(1.0, 0.2),
        "Release checklist, page three.": vector(1.0, 0.3),
        "Release notes without pages.": vector(1.0, 0.0)})
    return project


@pytest.mark.parametrize("query", [None, "release"], ids=["vector", "hybrid"])
async def test_search_filters_narrow_the_chunks_searched(uow, query):
    from ragolex.domain.models import SearchFilters

    project = await filtered_project(uow)

    async def search(**filters):
        hits = await uow.chunks.search(project.id, vector(1.0, 0.0), top_k=10, min_score=None,
                                       query=query, filters=SearchFilters(**filters))
        return sorted((hit.file_key, hit.chunk.index) for hit in hits)

    assert await search(file_keys=("n_notes.txt",)) == [("n_notes.txt", 0)]
    assert await search(page_from=2) == [("g_guide.pdf", 1), ("g_guide.pdf", 2)]
    assert await search(page_from=2, page_to=2) == [("g_guide.pdf", 1)]
    assert await search(metadata={"lang": "de"}) == [("g_guide.pdf", 2)]
    assert len(await search(max_per_file=1)) == 2
    assert await search(file_keys=("g_guide.pdf",), metadata={"lang": "en"}, page_to=1) == [
        ("g_guide.pdf", 0)]
    await uow.files.set_tags(project.id, "n_notes.txt", ["notes", "internal"])
    assert await search(tags=("internal", "missing")) == [("n_notes.txt", 0)]
    assert await search(tags=("missing",)) == []
    assert await search(tags=("notes",), file_keys=("g_guide.pdf",)) == []


async def test_search_filters_by_upload_date(uow):
    from datetime import UTC, datetime, timedelta

    from ragolex.domain.models import SearchFilters

    project = await filtered_project(uow)
    await uow.commit()
    now = datetime.now(UTC)

    later = await uow.chunks.search(project.id, vector(1.0, 0.0), top_k=10, min_score=None,
                                    filters=SearchFilters(uploaded_after=now + timedelta(hours=1)))
    earlier = await uow.chunks.search(
        project.id, vector(1.0, 0.0), top_k=10, min_score=None,
        filters=SearchFilters(uploaded_before=now + timedelta(hours=1)))

    assert later == []
    assert len(earlier) == 4


async def test_max_per_file_keeps_the_best_of_each_file_up_to_top_k(uow):
    from ragolex.domain.models import SearchFilters

    project = await filtered_project(uow)

    hits = await uow.chunks.search(project.id, vector(1.0, 0.0), top_k=3, min_score=None,
                                   filters=SearchFilters(max_per_file=2))

    assert [(hit.file_key, hit.chunk.index) for hit in hits] == [
        ("n_notes.txt", 0), ("g_guide.pdf", 0), ("g_guide.pdf", 1)]
