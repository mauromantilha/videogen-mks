"""Download seguro das saídas dos provedores (design/02 §7, RNF-07).

A URL vem do JSON do provedor e é tratada como NÃO confiável: só `https`, host na allowlist
(revalidada a cada redirect), tamanho máximo e nenhuma credencial. Injete um `httpx.AsyncClient`
dedicado, sem cabeçalhos de autenticação.
"""

import asyncio
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from videogen.core.errors import ProviderError
from videogen.core.retry import RetryPolicy, retry_async

CHUNK_SIZE = 1 << 16
MAX_REDIRECTS = 5
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class HttpDownloader:
    def __init__(self, client: httpx.AsyncClient, policy: RetryPolicy) -> None:
        self._client = client
        self._policy = policy

    async def fetch(
        self, url: str, dest: Path, *, allowed_hosts: Sequence[str], max_bytes: int
    ) -> None:
        async def once() -> None:
            await self._fetch_once(url, dest, allowed_hosts, max_bytes)

        await retry_async(once, self._policy, label="download")

    async def _fetch_once(
        self, url: str, dest: Path, allowed_hosts: Sequence[str], max_bytes: int
    ) -> None:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            ensure_allowed(current, allowed_hosts)
            try:
                async with self._client.stream("GET", current, follow_redirects=False) as resp:
                    if resp.is_redirect:
                        current = urljoin(current, resp.headers.get("location", ""))
                        continue
                    _check_status(resp)
                    await _stream_to_file(resp, dest, max_bytes)
                    return
            except httpx.TransportError as exc:
                raise ProviderError(
                    f"falha de rede no download: {type(exc).__name__}", retryable=True
                ) from exc
        raise ProviderError("redirecionamentos demais no download")


def ensure_allowed(url: str, allowed_hosts: Sequence[str]) -> None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password:
        raise ProviderError("URL de download recusada: exige https e sem credenciais")
    if not any(_host_matches(host, pattern.lower()) for pattern in allowed_hosts):
        raise ProviderError(f"host de download fora da allowlist: {host or '?'}")


def _host_matches(host: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        return host.endswith(pattern[1:]) and host != pattern[2:]
    return host == pattern


def _check_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    retryable = resp.status_code in _RETRYABLE_STATUS
    raise ProviderError(
        f"download respondeu HTTP {resp.status_code}", retryable=retryable, status=resp.status_code
    )


async def _stream_to_file(resp: httpx.Response, dest: Path, max_bytes: int) -> None:
    declared = int(resp.headers.get("content-length") or 0)
    if declared > max_bytes:
        raise ProviderError(f"download excede o limite ({declared} > {max_bytes} bytes)")
    partial = dest.with_name(f"{dest.name}.download")
    received = 0
    try:
        with partial.open("wb") as handle:
            async for chunk in resp.aiter_bytes(CHUNK_SIZE):
                received += len(chunk)
                if received > max_bytes:
                    raise ProviderError(f"download excede o limite de {max_bytes} bytes")
                await asyncio.to_thread(handle.write, chunk)
        if received == 0:
            raise ProviderError("download vazio", retryable=True)
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)
