"""Cliente HTTP dos provedores: JSON, timeouts por chamada e retry (RNF-04).

Um `httpx.AsyncClient` por provedor, já com o cabeçalho de autenticação; nada aqui loga
cabeçalhos ou corpos de requisição (segredos e prompts ficam fora dos logs).
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from videogen.core.errors import ProviderError
from videogen.core.retry import RetryPolicy, Sleep, retry_async
from videogen.providers.http.errors import classify_response, transport_error

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class HttpCall:
    method: str
    url: str
    idempotent: bool  # False: só repete falhas anteriores ao aceite do pedido
    json_body: JsonObject | None = None
    timeout_s: float | None = None


class ResilientHttpClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        policy: RetryPolicy,
        *,
        provider: str,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._client = client
        self._policy = policy
        self.provider = provider
        self._sleep = sleep

    async def request[T](self, call: HttpCall, parse: Callable[[JsonObject], T]) -> T:
        """Faz a chamada com retry; `parse` roda dentro da tentativa (pode pedir retry)."""

        async def once() -> T:
            return parse(_decode(await self._send(call), self.provider))

        label = f"{self.provider} {call.method}"
        return await retry_async(once, self._policy, sleep=self._sleep, label=label)

    async def request_json(self, call: HttpCall) -> JsonObject:
        return await self.request(call, _identity)

    async def _send(self, call: HttpCall) -> httpx.Response:
        timeout = (
            httpx.Timeout(call.timeout_s, connect=10.0)
            if call.timeout_s
            else httpx.USE_CLIENT_DEFAULT
        )
        try:
            response = await self._client.request(
                call.method, call.url, json=call.json_body, timeout=timeout
            )
        except httpx.TransportError as exc:
            raise transport_error(exc, provider=self.provider, idempotent=call.idempotent) from exc
        if response.is_error:
            raise classify_response(
                response.status_code, response.text, response.headers, provider=self.provider
            )
        return response


def _identity(data: JsonObject) -> JsonObject:
    return data


def _decode(response: httpx.Response, provider: str) -> JsonObject:
    text = response.text.strip()  # DeepSeek envia linhas em branco de keep-alive antes do JSON
    if not text:
        raise ProviderError(f"{provider}: resposta vazia", retryable=True)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProviderError(f"{provider}: resposta não é JSON") from exc
    if not isinstance(data, dict):
        raise ProviderError(f"{provider}: JSON inesperado ({type(data).__name__})")
    return data
