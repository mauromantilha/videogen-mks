"""Ciclo de vida de uma predição paga: retomar, submeter, aguardar, extrair a saída.

Contrato de retomada (RNF-09): `ctx.on_submitted(id)` roda logo após o create e antes do
primeiro poll. Com `ctx.resume_remote_id`, nada é reenviado — só retoma o polling.
Predição `failed` transitória vira nova submissão (conta nas tentativas).
"""

import logging
import re
from typing import Any

from videogen.core.errors import ContentRejected, ProviderError, ProviderTimeout
from videogen.domain.catalog import ModelSpec
from videogen.domain.generation import GenerationResult, RunContext
from videogen.providers.http.errors import looks_like_content_rejection
from videogen.providers.replicate.client import Prediction, ReplicateClient

logger = logging.getLogger(__name__)
_TRANSIENT = re.compile(r"E1001|E6716|E9243|E8765|out of memory|CUDA|timed? ?out|cold", re.I)


class PredictionRunner:
    def __init__(self, client: ReplicateClient, *, max_attempts: int = 3) -> None:
        self._client = client
        self._max_attempts = max_attempts

    async def run(
        self, spec: ModelSpec, payload: dict[str, Any], ctx: RunContext
    ) -> GenerationResult:
        remote_id = ctx.resume_remote_id
        for attempt in range(1, self._max_attempts + 1):
            if remote_id is None:
                created = await self._client.create(spec.remote_ref, spec.version, payload)
                remote_id = created.id
                await ctx.on_submitted(remote_id)
            final = await self._wait(remote_id, ctx.timeout_s)
            if final.status == "succeeded":
                return _result(spec, final)
            error = _failure(final)
            if not error.retryable or attempt == self._max_attempts:
                raise error
            logger.warning(
                "predição falhou; nova submissão",
                extra={"remote_id": remote_id, "attempt": attempt},
            )
            remote_id = None
        raise AssertionError("inalcançável")  # pragma: no cover

    async def cancel(self, remote_id: str) -> None:
        await self._client.cancel(remote_id)

    async def _wait(self, remote_id: str, timeout_s: float) -> Prediction:
        try:
            return await self._client.wait(remote_id, timeout_s=timeout_s)
        except ProviderTimeout:
            await self._client.cancel(remote_id)  # para de cobrar GPU
            raise


def _failure(prediction: Prediction) -> ProviderError:
    detail = str(prediction.error or prediction.status)[:300]
    message = f"predição {prediction.id} terminou como {prediction.status}: {detail}"
    if looks_like_content_rejection(detail):
        return ContentRejected(message, remote_id=prediction.id)
    retryable = prediction.status == "aborted" or bool(_TRANSIENT.search(detail))
    return ProviderError(message, retryable=retryable, remote_id=prediction.id)


def _result(spec: ModelSpec, prediction: Prediction) -> GenerationResult:
    seconds = prediction.metrics.get("predict_time")
    return GenerationResult(
        remote_id=prediction.id,
        output_url=extract_url(prediction.output),
        cost_usd=spec.price.actual(seconds=seconds),
        provider_seconds=seconds,
    )


def extract_url(output: Any) -> str:
    """Saída de arquivo pode vir como URL, lista de URLs ou objeto com `url`/`audio`/`video`."""
    if isinstance(output, str) and output.startswith("https://"):
        return output
    if isinstance(output, list):
        for item in output:
            if found := _try_extract(item):
                return found
    if isinstance(output, dict):
        for key in ("url", "audio", "video", "audio_out", "output"):
            if found := _try_extract(output.get(key)):
                return found
    raise ProviderError(f"saída sem URL de arquivo: {str(output)[:120]}")


def _try_extract(value: Any) -> str | None:
    try:
        return extract_url(value) if value is not None else None
    except ProviderError:
        return None
