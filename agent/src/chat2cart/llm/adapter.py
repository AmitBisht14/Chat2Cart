import asyncio
from collections.abc import Callable
from typing import Protocol, Self

from langchain.chat_models import init_chat_model
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel, ValidationError

from chat2cart.config import Settings
from chat2cart.secrets import LLM_API_KEY, SecretStore

LLM_TIMEOUT_SECONDS = 30.0
MODEL_TEMPERATURE = 0


class LLMError(Exception):
    """Base class for every language model failure."""


class LLMNotConfiguredError(LLMError):
    """The model cannot be used yet: its API key is missing."""


class LLMTimeoutError(LLMError):
    """The model did not answer in time."""


class LLMInvalidOutputError(LLMError):
    """The model answered, but not in the shape the schema asks for."""


class ChatModel(Protocol):
    def with_structured_output(
        self, schema: type[BaseModel]
    ) -> Runnable[list[BaseMessage], object]: ...


class StructuredLLM(Protocol):
    """What the rest of the code asks of a language model: data in a schema, never tool calls."""

    async def structured[SchemaT: BaseModel](
        self, schema: type[SchemaT], system: str, user: str
    ) -> SchemaT: ...


class LLMAdapter:
    def __init__(self, model: ChatModel, timeout_seconds: float = LLM_TIMEOUT_SECONDS) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        store: SecretStore,
        build_model: Callable[..., ChatModel] = init_chat_model,
    ) -> Self:
        api_key = store.get(LLM_API_KEY)
        if api_key is None:
            raise LLMNotConfiguredError(
                "No language model API key is stored. Run chat2cart secrets set llm-api-key."
            )
        model = build_model(
            settings.llm_model,
            model_provider=settings.llm_provider,
            api_key=api_key,
            temperature=MODEL_TEMPERATURE,
        )
        return cls(model)

    async def structured[SchemaT: BaseModel](
        self, schema: type[SchemaT], system: str, user: str
    ) -> SchemaT:
        """Ask the model for an answer in `schema`. The model gets no tools."""
        runnable = self._model.with_structured_output(schema)
        messages: list[BaseMessage] = [SystemMessage(system), HumanMessage(user)]
        # A worker thread and the sync client: LangChain caches its async HTTP client, which
        # outlives the event loop of one cart job (each job runs in its own asyncio.run).
        call = asyncio.to_thread(runnable.invoke, messages)
        try:
            result = await asyncio.wait_for(call, self._timeout_seconds)
        except TimeoutError as error:
            raise LLMTimeoutError(
                f"The language model did not answer within {self._timeout_seconds:g} seconds."
            ) from error
        return _validated(schema, result)


def _validated[SchemaT: BaseModel](schema: type[SchemaT], result: object) -> SchemaT:
    if isinstance(result, schema):
        return result
    if isinstance(result, dict):
        return _from_dict(schema, result)
    raise _invalid(schema)


def _from_dict[SchemaT: BaseModel](schema: type[SchemaT], result: dict[str, object]) -> SchemaT:
    try:
        return schema.model_validate(result)
    except ValidationError:
        # Dropped on purpose: pydantic's message would echo what the model said.
        raise _invalid(schema) from None


def _invalid(schema: type[BaseModel]) -> LLMInvalidOutputError:
    return LLMInvalidOutputError(f"The language model's answer did not match {schema.__name__}.")
