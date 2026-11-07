from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class LLMCall:
    schema: type[BaseModel]
    system: str
    user: str


class FakeLLM:
    """A StructuredLLM that returns scripted answers or raises scripted errors, in order."""

    def __init__(self, *script: BaseModel | Exception) -> None:
        self._script = list(script)
        self.calls: list[LLMCall] = []

    async def structured[SchemaT: BaseModel](
        self, schema: type[SchemaT], system: str, user: str
    ) -> SchemaT:
        self.calls.append(LLMCall(schema, system, user))
        outcome = self._script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if not isinstance(outcome, schema):
            raise AssertionError(
                f"FakeLLM was scripted with {type(outcome).__name__}, not {schema.__name__}"
            )
        return outcome
