from dataclasses import dataclass
from typing import Literal

from ragolex.core.errors import ConversationNotFound, MessageNotFound, ProjectNotFound
from ragolex.domain.models import (
    Conversation,
    ConversationMessage,
    Feedback,
    FeedbackCounts,
    Project,
    RatedAnswer,
)
from ragolex.domain.repositories import UnitOfWork
from ragolex.services.project_service import Page


@dataclass(frozen=True)
class ConversationWithMessages:
    conversation: Conversation
    messages: list[ConversationMessage]


@dataclass(frozen=True)
class FeedbackPage:
    """A page of rated answers, and how many of each rating the project has."""

    page: Page[RatedAnswer]
    counts: FeedbackCounts


class ConversationService:
    """Starts, lists, reads and deletes a project's conversations, and rates answers.

    Questions are asked in a conversation through the AnswerService.
    """

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    async def create(self, project_name: str, title: str | None = None) -> Conversation:
        project = await self._project(project_name)
        conversation = await self.uow.conversations.create(project.id, title)
        await self.uow.commit()
        return conversation

    async def list(self, project_name: str, offset: int, limit: int) -> Page[Conversation]:
        project = await self._project(project_name)
        return Page(
            items=await self.uow.conversations.list_for_project(project.id, offset=offset,
                                                                limit=limit),
            total=await self.uow.conversations.count_for_project(project.id),
            offset=offset, limit=limit,
        )

    async def get(self, project_name: str, conversation_id: str) -> ConversationWithMessages:
        project = await self._project(project_name)
        conversation = await self.uow.conversations.get(project.id, conversation_id)
        if conversation is None:
            raise ConversationNotFound()
        return ConversationWithMessages(
            conversation=conversation,
            messages=await self.uow.conversations.messages(conversation.id))

    async def delete(self, project_name: str, conversation_id: str) -> None:
        project = await self._project(project_name)
        if not await self.uow.conversations.delete(project.id, conversation_id):
            raise ConversationNotFound()
        await self.uow.commit()

    async def rate(self, project_name: str, conversation_id: str, message_id: int,
                   rating: Literal["up", "down"], comment: str | None) -> ConversationMessage:
        """Give an answer thumbs up or down, replacing any rating it had."""
        await self._answer(project_name, conversation_id, message_id)
        await self.uow.conversations.set_feedback(
            message_id, Feedback(rating=rating, comment=(comment or "").strip() or None))
        await self.uow.commit()
        rated = await self.uow.conversations.get_message(conversation_id, message_id)
        if rated is None:
            raise MessageNotFound()  # Deleted meanwhile.
        return rated

    async def unrate(self, project_name: str, conversation_id: str, message_id: int) -> None:
        await self._answer(project_name, conversation_id, message_id)
        await self.uow.conversations.set_feedback(message_id, None)
        await self.uow.commit()

    async def feedback(self, project_name: str, rating: str | None, offset: int,
                       limit: int) -> FeedbackPage:
        project = await self._project(project_name)
        counts = await self.uow.conversations.count_feedback(project.id)
        total = (counts.up if rating == "up" else counts.down if rating == "down"
                 else counts.up + counts.down)
        items = await self.uow.conversations.rated_answers(project.id, rating=rating,
                                                           offset=offset, limit=limit)
        return FeedbackPage(page=Page(items=items, total=total, offset=offset, limit=limit),
                            counts=counts)

    async def _answer(self, project_name: str, conversation_id: str,
                      message_id: int) -> ConversationMessage:
        project = await self._project(project_name)
        if await self.uow.conversations.get(project.id, conversation_id) is None:
            raise ConversationNotFound()
        message = await self.uow.conversations.get_message(conversation_id, message_id)
        if message is None or message.role != "assistant":
            raise MessageNotFound()
        return message

    async def _project(self, name: str) -> Project:
        project = await self.uow.projects.get_by_name(name)
        if project is None:
            raise ProjectNotFound()
        return project
