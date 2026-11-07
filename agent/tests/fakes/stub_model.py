from collections.abc import Awaitable, Callable

from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel


class StubModel:
    """Stands in for a LangChain chat model: with_structured_output gives a runnable."""

    def __init__(self, respond: Callable[[list[BaseMessage]], Awaitable[object]]) -> None:
        self._respond = respond

    def with_structured_output(
        self, schema: type[BaseModel]
    ) -> Runnable[list[BaseMessage], object]:
        return RunnableLambda(self._respond)


def answering(result: object) -> StubModel:
    async def respond(_messages: list[BaseMessage]) -> object:
        return result

    return StubModel(respond)
