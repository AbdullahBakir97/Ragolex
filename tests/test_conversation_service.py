import pytest

from ragolex.core.errors import ConversationNotFound, LLMFailed, ProjectNotFound
from ragolex.domain.llm import TokenPrices, TokenUsage
from ragolex.domain.models import Chunk
from ragolex.services.answer_service import HISTORY_MESSAGES, AnswerService
from ragolex.services.conversation_service import ConversationService
from ragolex.services.indexing_service import IndexingService
from ragolex.services.search_service import SearchService

from .fakes import FAKE_USAGE, FakeEmbedder, FakeLLM, FakeUnitOfWork

pytestmark = pytest.mark.anyio

TEXTS = ["Cats purr and sleep all day.",
         "Postgres stores vectors with pgvector.",
         "Dogs bark at cats."]


@pytest.fixture
async def uow():
    uow = FakeUnitOfWork()
    project = await uow.projects.get_or_create("p1")
    await uow.projects.get_or_create("other")
    record = await uow.files.add(project_id=project.id, key="a_notes.txt", original_name="notes.txt",
                                 content_type="text/plain", size_bytes=0)
    await uow.chunks.replace_for_file(record, [Chunk(i, text, {"source": "a_notes.txt"})
                                               for i, text in enumerate(TEXTS)])
    await IndexingService(uow, FakeEmbedder(), batch_size=10).index("p1")
    return uow


def answers(uow, llm, prices=None):
    return AnswerService(SearchService(uow, FakeEmbedder()), llm, uow, min_score=0.2, prices=prices)


async def start(uow, project="p1"):
    return await ConversationService(uow).create(project)


async def test_the_first_question_is_not_rewritten_and_is_kept_with_its_answer(uow):
    conversation = await start(uow)
    llm = FakeLLM("Cats purr [1].")

    answer = await answers(uow, llm).ask("p1", "Do cats purr?", top_k=5,
                                         conversation_id=conversation.id)

    assert len(llm.calls) == 1  # only the answer, nothing to rewrite
    assert (answer.conversation_id, answer.search_question) == (conversation.id, None)
    found = await ConversationService(uow).get("p1", conversation.id)
    assert found.conversation.title == "Do cats purr?"
    question, reply = found.messages
    assert (question.role, question.content) == ("user", "Do cats purr?")
    assert (reply.role, reply.content, reply.prompt_version) == ("assistant", "Cats purr [1].",
                                                                 "answer-v1")
    [citation] = reply.citations
    assert (citation.number, citation.text, citation.file_key) == (1, answer.citations[0].source.chunk.text,
                                                                   "a_notes.txt")


async def test_a_follow_up_is_rewritten_searched_and_answered_with_the_history(uow):
    conversation = await start(uow)
    await answers(uow, FakeLLM("Cats purr [1].")).ask("p1", "Do cats purr?", top_k=5,
                                                      conversation_id=conversation.id)
    llm = FakeLLM(replies=["What do dogs do to cats?", "Dogs bark at cats [1]."])

    answer = await answers(uow, llm).ask("p1", "And dogs?", top_k=1,
                                         conversation_id=conversation.id)

    rewrite, reply = llm.calls
    assert "User: Do cats purr?\nAssistant: Cats purr [1]." in rewrite[1].content
    assert "<question>\nAnd dogs?\n</question>" in rewrite[1].content
    # The rewritten question found the source; the answer saw the history without old markers.
    assert answer.search_question == "What do dogs do to cats?"
    assert answer.citations[0].source.chunk.text == "Dogs bark at cats."
    assert [m.role for m in reply] == ["system", "user", "assistant", "user"]
    assert reply[2].content == "Cats purr."
    assert "<question>\nWhat do dogs do to cats?\n</question>" in reply[3].content
    # Rewriting is part of the answer's cost.
    assert answer.usage == TokenUsage(2 * FAKE_USAGE.input_tokens, 2 * FAKE_USAGE.output_tokens)
    found = await ConversationService(uow).get("p1", conversation.id)
    assert [m.content for m in found.messages] == ["Do cats purr?", "Cats purr [1].", "And dogs?",
                                                   "Dogs bark at cats [1]."]
    assert found.messages[-1].search_question == "What do dogs do to cats?"
    assert found.conversation.title == "Do cats purr?"  # the first question stays the title


async def test_a_question_the_rewrite_keeps_has_no_search_question(uow):
    conversation = await start(uow)
    await answers(uow, FakeLLM("Cats purr [1].")).ask("p1", "Do cats purr?", top_k=5,
                                                      conversation_id=conversation.id)
    llm = FakeLLM(replies=["Do dogs bark?", "Dogs bark [1]."])

    answer = await answers(uow, llm).ask("p1", "Do dogs bark?", top_k=5,
                                         conversation_id=conversation.id)

    assert answer.search_question is None


async def test_no_answer_is_kept_and_shown_to_the_model_as_such(uow):
    conversation = await start(uow)
    await answers(uow, FakeLLM()).ask("p1", "Where is Paris?", top_k=5,
                                      conversation_id=conversation.id)
    llm = FakeLLM(replies=["Do cats purr?", "Cats purr [1]."])

    await answers(uow, llm).ask("p1", "And cats?", top_k=5, conversation_id=conversation.id)

    found = await ConversationService(uow).get("p1", conversation.id)
    assert [(m.role, m.content) for m in found.messages[:2]] == [("user", "Where is Paris?"),
                                                                 ("assistant", None)]
    assert "Assistant: NO_ANSWER" in llm.calls[0][1].content


async def test_only_the_last_messages_are_history(uow):
    conversation = await start(uow)
    for i in range(5):
        await answers(uow, FakeLLM(replies=["Do cats purr?", f"Cats purr {i} [1]."])).ask(
            "p1", f"Question {i} about cats?", top_k=5, conversation_id=conversation.id)
    llm = FakeLLM(replies=["Do cats purr?", "Cats purr [1]."])

    await answers(uow, llm).ask("p1", "And then?", top_k=5, conversation_id=conversation.id)

    answer_messages = llm.calls[1]
    assert len(answer_messages) == 1 + HISTORY_MESSAGES + 1
    assert answer_messages[1].content == "Question 2 about cats?"


async def test_streaming_in_a_conversation_keeps_the_turn_when_it_completes(uow):
    conversation = await start(uow)
    service = answers(uow, FakeLLM("Cats purr [1].", piece_size=3))

    prepared = await service.prepare("p1", "Do cats purr?", top_k=5,
                                     conversation_id=conversation.id)
    events = [event async for event in service.stream(prepared)]

    assert events[-1].conversation_id == conversation.id
    found = await ConversationService(uow).get("p1", conversation.id)
    assert [m.content for m in found.messages] == ["Do cats purr?", "Cats purr [1]."]


async def test_a_failed_answer_keeps_nothing(uow):
    conversation = await start(uow)
    service = answers(uow, FakeLLM("Cats purr all day [1].", fail_after=1))
    prepared = await service.prepare("p1", "Do cats purr?", top_k=5,
                                     conversation_id=conversation.id)

    with pytest.raises(LLMFailed):
        async for _ in service.stream(prepared):
            pass

    found = await ConversationService(uow).get("p1", conversation.id)
    assert found.messages == []


async def test_the_rewrite_alone_is_a_model_call_with_a_cost(uow):
    conversation = await start(uow)
    await answers(uow, FakeLLM("Cats purr [1].")).ask("p1", "Do cats purr?", top_k=5,
                                                      conversation_id=conversation.id)
    prices = TokenPrices(input_per_million=0.4, output_per_million=1.6)

    answer = await answers(uow, FakeLLM(replies=["Where is Paris?"]), prices=prices).ask(
        "p1", "And Paris?", top_k=5, conversation_id=conversation.id)

    assert answer.text is None
    assert answer.usage == FAKE_USAGE and answer.cost_usd == pytest.approx(prices.cost(FAKE_USAGE))
    assert uow.answers.records[-1].model == "fake-llm"


async def test_another_projects_conversation_is_not_found(uow):
    conversation = await start(uow, project="other")

    with pytest.raises(ConversationNotFound):
        await answers(uow, FakeLLM()).ask("p1", "Do cats purr?", top_k=5,
                                          conversation_id=conversation.id)
    with pytest.raises(ConversationNotFound):
        await ConversationService(uow).get("p1", conversation.id)
    with pytest.raises(ConversationNotFound):
        await ConversationService(uow).delete("p1", conversation.id)


async def test_conversations_are_listed_newest_first_and_deleted(uow):
    service = ConversationService(uow)
    first = await service.create("p1")
    second = await service.create("p1", title="Named")
    await answers(uow, FakeLLM("Cats purr [1].")).ask("p1", "Do cats purr?", top_k=5,
                                                      conversation_id=first.id)

    page = await service.list("p1", offset=0, limit=10)

    assert ([c.id for c in page.items], page.total) == ([first.id, second.id], 2)
    assert second.title == "Named"
    await service.delete("p1", first.id)
    assert (await service.list("p1", offset=0, limit=10)).total == 1
    with pytest.raises(ProjectNotFound):
        await service.create("missing")


async def test_long_first_questions_make_short_titles(uow):
    conversation = await start(uow)

    await answers(uow, FakeLLM("Cats purr [1].")).ask("p1", "Do cats purr " + "really " * 20 + "?",
                                                      top_k=5, conversation_id=conversation.id)

    title = (await ConversationService(uow).get("p1", conversation.id)).conversation.title
    assert len(title) == 80 and title.endswith("…")


async def rated_conversation(uow):
    from ragolex.domain.models import ConversationMessage

    project = await uow.projects.get_by_name("p1")
    conversation = await uow.conversations.create(project.id, None)
    question, answer = await uow.conversations.add_messages(conversation.id, [
        ConversationMessage(role="user", content="Do cats purr?"),
        ConversationMessage(role="assistant", content="Yes [1]."),
    ])
    return conversation, question, answer


async def test_answers_are_rated_and_listed(uow):
    conversation, _, answer = await rated_conversation(uow)
    service = ConversationService(uow)

    rated = await service.rate("p1", conversation.id, answer, "down", "  ")
    feedback = await service.feedback("p1", None, offset=0, limit=10)

    assert (rated.feedback.rating, rated.feedback.comment) == ("down", None)
    assert (feedback.counts.up, feedback.counts.down, feedback.page.total) == (0, 1, 1)
    assert feedback.page.items[0].question == "Do cats purr?"
    assert (await service.feedback("p1", "up", offset=0, limit=10)).page.total == 0

    await service.unrate("p1", conversation.id, answer)
    assert (await service.feedback("p1", None, offset=0, limit=10)).page.total == 0


async def test_only_answers_of_the_projects_conversations_can_be_rated(uow):
    from ragolex.core.errors import MessageNotFound

    conversation, question, answer = await rated_conversation(uow)
    service = ConversationService(uow)

    with pytest.raises(MessageNotFound):
        await service.rate("p1", conversation.id, question, "up", None)
    with pytest.raises(MessageNotFound):
        await service.rate("p1", conversation.id, 999, "up", None)
    with pytest.raises(ConversationNotFound):
        await service.rate("other", conversation.id, answer, "up", None)
    with pytest.raises(ProjectNotFound):
        await service.unrate("nope", conversation.id, answer)
