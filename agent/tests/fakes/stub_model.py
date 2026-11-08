import asyncio
from collections.abc import Callable

from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel


class StubModel:
    """Stands in for a LangChain chat model: with_structured_output gives a runnable."""

    def __init__(self, respond: Callable[[list[BaseMessage]], object]) -> None:
        self._respond = respond

    def with_structured_output(
        self, schema: type[BaseModel]
    ) -> Runnable[list[BaseMessage], object]:
        return RunnableLambda(self._respond)


def answering(result: object) -> StubModel:
    def respond(_messages: list[BaseMessage]) -> object:
        return result

    return StubModel(respond)


class LoopBoundModel:
    """A chat model whose async client stays bound to the first event loop it ran in."""

    def __init__(self, result: object) -> None:
        self._result = result
        self._first_loop: asyncio.AbstractEventLoop | None = None

    def with_structured_output(
        self, schema: type[BaseModel]
    ) -> Runnable[list[BaseMessage], object]:
        return RunnableLambda(self._invoke, afunc=self._ainvoke)

    def _invoke(self, _messages: list[BaseMessage]) -> object:
        return self._result

    async def _ainvoke(self, _messages: list[BaseMessage]) -> object:
        self._first_loop = self._first_loop or asyncio.get_running_loop()
        if self._first_loop.is_closed():
            raise RuntimeError("Event loop is closed")
        return self._result
