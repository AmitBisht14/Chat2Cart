import asyncio
from collections.abc import Awaitable, Callable

import pytest
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from chat2cart.config import load_settings
from chat2cart.llm.adapter import (
    LLMAdapter,
    LLMInvalidOutputError,
    LLMNotConfiguredError,
    LLMTimeoutError,
)
from chat2cart.secrets import LLM_API_KEY, InMemorySecretStore


class Answer(BaseModel):
    label: str


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


def test_a_valid_result_is_returned_as_the_schema_instance() -> None:
    adapter = LLMAdapter(answering(Answer(label="order")))

    result = asyncio.run(adapter.structured(Answer, "system text", "user text"))

    assert result == Answer(label="order")


def test_the_model_gets_the_system_and_user_messages_and_no_tools() -> None:
    seen: list[list[BaseMessage]] = []

    async def respond(messages: list[BaseMessage]) -> object:
        seen.append(messages)
        return Answer(label="order")

    asyncio.run(LLMAdapter(StubModel(respond)).structured(Answer, "system text", "user text"))

    assert seen == [[SystemMessage("system text"), HumanMessage("user text")]]


def test_a_dict_result_is_validated_against_the_schema() -> None:
    adapter = LLMAdapter(answering({"label": "general"}))

    assert asyncio.run(adapter.structured(Answer, "s", "u")) == Answer(label="general")


def test_a_slow_model_raises_a_timeout_error() -> None:
    async def slow(_messages: list[BaseMessage]) -> object:
        await asyncio.sleep(5)
        return Answer(label="late")

    adapter = LLMAdapter(StubModel(slow), timeout_seconds=0.01)

    with pytest.raises(LLMTimeoutError):
        asyncio.run(adapter.structured(Answer, "s", "u"))


@pytest.mark.parametrize("bad", [None, {"wrong_field": "x"}, "plain text", 42])
def test_invalid_output_raises_an_error_naming_only_the_schema(bad: object) -> None:
    adapter = LLMAdapter(answering(bad))

    with pytest.raises(LLMInvalidOutputError) as error_info:
        asyncio.run(adapter.structured(Answer, "s", "u"))

    assert str(error_info.value) == "The language model's answer did not match Answer."


def test_from_settings_reads_the_key_from_the_store_and_uses_the_configured_model(
    valid_env: dict[str, str],
) -> None:
    store = InMemorySecretStore()
    store.set(LLM_API_KEY, "secret-key")
    built: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def build_model(*args: object, **kwargs: object) -> StubModel:
        built.append((args, kwargs))
        return answering(Answer(label="order"))

    adapter = LLMAdapter.from_settings(load_settings(env_file=None), store, build_model)

    assert built == [
        (
            ("test-model",),
            {"model_provider": "anthropic", "api_key": "secret-key", "temperature": 0},
        )
    ]
    assert asyncio.run(adapter.structured(Answer, "s", "u")) == Answer(label="order")


def test_from_settings_without_a_stored_key_says_how_to_add_one(valid_env: dict[str, str]) -> None:
    with pytest.raises(LLMNotConfiguredError, match="secrets set llm-api-key"):
        LLMAdapter.from_settings(load_settings(env_file=None), InMemorySecretStore())
