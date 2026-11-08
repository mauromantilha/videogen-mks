"""Port do LLM roteirista (Etapa 1)."""

from collections.abc import Sequence
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(extra="forbid", frozen=True)


class ChatMessage(BaseModel):
    model_config = _FROZEN

    role: Literal["system", "user", "assistant"]
    content: str


class LLMUsage(BaseModel):
    model_config = _FROZEN

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)


class LLMResult(BaseModel):
    model_config = _FROZEN

    text: str
    usage: LLMUsage = Field(default_factory=LLMUsage)
    cost_usd: float = Field(default=0.0, ge=0)


@runtime_checkable
class LLMProvider(Protocol):
    async def complete(
        self, messages: Sequence[ChatMessage], *, json_mode: bool, temperature: float | None
    ) -> LLMResult: ...
