"""A Python client for the Ragolex API, generated from its OpenAPI schema.

    from ragolex_client import Ragolex

    with Ragolex("https://rag.example.com", api_key="mrag_…") as rag:
        rag.add_document("handbook", "leave-policy.pdf", tags=["hr"])
        answer = rag.ask_project("handbook", question="How many days of leave?")
"""

from . import models
from ._types import UNSET, Unset
from .client import AnswerDelta, AnswerDone, AnswerEvent, AsyncRagolex, Ragolex
from .errors import RagolexError

__all__ = ["UNSET", "AnswerDelta", "AnswerDone", "AnswerEvent", "AsyncRagolex", "Ragolex",
           "RagolexError", "Unset", "models"]
__version__ = "0.1.0"
