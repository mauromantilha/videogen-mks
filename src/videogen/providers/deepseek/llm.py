"""LLM compatível com OpenAI (DeepSeek; reutilizado para DeepInfra via `base_url`).

Capacidades vêm do `ModelSpec` (YAML), não do código: `json_mode`, `temperature`,
`thinking` ("enabled"/"disabled") e `base_url`. Em thinking mode a API ignora `temperature`.
"""

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from videogen.core.errors import ContentRejected, ProviderError
from videogen.domain.catalog import ModelSpec
from videogen.ports.llm import ChatMessage, LLMResult, LLMUsage
from videogen.providers.http.client import HttpCall, JsonObject, ResilientHttpClient

DEFAULT_BASE_URL = "https://api.deepseek.com"
_LENIENT = ConfigDict(extra="ignore")


class _Message(BaseModel):
    model_config = _LENIENT
    content: str | None = None


class _Choice(BaseModel):
    model_config = _LENIENT
    message: _Message
    finish_reason: str | None = None


class _Usage(BaseModel):
    model_config = _LENIENT
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _Completion(BaseModel):
    model_config = _LENIENT
    choices: list[_Choice]
    usage: _Usage = _Usage()


class OpenAICompatibleLLM:
    def __init__(self, http: ResilientHttpClient, spec: ModelSpec) -> None:
        self._http = http
        self._spec = spec
        base_url = str(spec.capabilities.get("base_url") or DEFAULT_BASE_URL)
        self._url = f"{base_url.rstrip('/')}/chat/completions"

    async def complete(
        self, messages: Sequence[ChatMessage], *, json_mode: bool, temperature: float | None
    ) -> LLMResult:
        call = HttpCall(
            "POST",
            self._url,
            idempotent=True,  # repetir uma chamada de LLM custa centavos; ok repetir
            json_body=self._body(messages, json_mode, temperature),
            timeout_s=self._spec.timeouts.total_s,
        )
        completion = await self._http.request(call, self._parse)
        usage = completion.usage
        cost = self._spec.price.actual(
            prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens
        )
        return LLMResult(
            text=completion.choices[0].message.content or "",
            usage=LLMUsage(
                prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens
            ),
            cost_usd=cost,
        )

    def _body(
        self, messages: Sequence[ChatMessage], json_mode: bool, temperature: float | None
    ) -> JsonObject:
        caps = self._spec.capabilities
        body: dict[str, Any] = {
            "model": self._spec.remote_ref,
            "messages": [message.model_dump() for message in messages],
            "stream": False,
        }
        body.update(self._spec.defaults)  # ex.: max_tokens
        thinking = caps.get("thinking")
        if isinstance(thinking, str):
            body["thinking"] = {"type": thinking}
        if json_mode and caps.get("json_mode"):
            body["response_format"] = {"type": "json_object"}
        if temperature is not None and caps.get("temperature", True) and thinking != "enabled":
            body["temperature"] = temperature
        return body

    def _parse(self, data: JsonObject) -> _Completion:
        completion = _Completion.model_validate(data)
        if not completion.choices:
            raise ProviderError(f"{self._http.provider}: resposta sem choices", retryable=True)
        choice = completion.choices[0]
        if choice.finish_reason == "content_filter":
            raise ContentRejected(f"{self._http.provider}: conteúdo bloqueado pelo filtro")
        if choice.finish_reason == "insufficient_system_resource":
            raise ProviderError(f"{self._http.provider}: sem recursos", retryable=True)
        if not (choice.message.content or "").strip():
            # JSON mode pode trocar saída inválida por espaços: vale nova tentativa.
            raise ProviderError(f"{self._http.provider}: conteúdo vazio", retryable=True)
        return completion
