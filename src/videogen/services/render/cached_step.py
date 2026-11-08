"""O coração da idempotência (design/05 §5.4): cache → retomada → provedor → download → commit.

- Hash no cache ⇒ nenhuma chamada paga.
- Mesmo hash em voo ⇒ single-flight (uma chamada para as duas cenas).
- `remote_id` gravado no submit ⇒ após crash/retry, retoma o polling em vez de reenviar.
- Falha do provedor ⇒ `remote_id` limpo (a próxima tentativa cria outra predição).
  Falha no download ⇒ `remote_id` mantido (a predição já foi paga; basta baixar de novo).
- Cancelamento ⇒ cancela a predição remota (best-effort) para parar a cobrança de GPU.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from videogen.core.errors import ProviderError
from videogen.domain.catalog import ModelSpec
from videogen.domain.generation import GenerationResult, RunContext
from videogen.domain.media import ArtifactKind
from videogen.ports.cache import ArtifactCache
from videogen.ports.downloader import Downloader
from videogen.ports.probe import MediaProbe
from videogen.services.render.single_flight import SingleFlight
from videogen.services.render.step_tracker import StepRef, StepTracker

logger = logging.getLogger(__name__)
Produce = Callable[[RunContext], Awaitable[GenerationResult]]
Cancel = Callable[[str], Awaitable[None]]
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
CANCEL_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class Produced:
    path: Path
    cost_usd: float
    fresh: bool  # False = veio do cache ou de outra cena em voo (custo zero aqui)


@dataclass(frozen=True)
class PaidCall:
    kind: ArtifactKind
    key: str
    spec: ModelSpec
    produce: Produce
    cancel: Cancel


class CachedStep:
    def __init__(
        self, cache: ArtifactCache, downloader: Downloader, probe: MediaProbe,
        tracker: StepTracker, flight: SingleFlight,
    ) -> None:  # fmt: skip
        self._cache, self._downloader, self._probe = cache, downloader, probe
        self._tracker, self._flight = tracker, flight

    async def fetch(self, call: PaidCall, ref: StepRef) -> Produced:
        if (hit := self._cache.get(call.kind, call.key)) is not None:
            return Produced(hit, 0.0, fresh=False)
        if self._flight.is_inflight(call.key):
            shared = await self._flight.run(call.key, lambda: self._produce(call, ref))
            return Produced(shared.path, 0.0, fresh=False)
        return await self._flight.run(call.key, lambda: self._produce(call, ref))

    async def _produce(self, call: PaidCall, ref: StepRef) -> Produced:
        if (hit := self._cache.get(call.kind, call.key)) is not None:
            return Produced(hit, 0.0, fresh=False)
        await self._tracker.started(ref, paid=True)
        result = await self._call_provider(call, ref)
        tmp = self._cache.tmp_path(call.kind, call.key)
        try:
            await self._downloader.fetch(result.output_url, tmp,
                                         allowed_hosts=call.spec.allowed_hosts,
                                         max_bytes=MAX_DOWNLOAD_BYTES)  # fmt: skip
            await self._probe.validate(tmp, call.kind)
            meta = {"remote_id": result.remote_id, "model": call.spec.key,
                    "version": call.spec.model_version, "cost_usd": result.cost_usd}  # fmt: skip
            path = self._cache.commit(call.kind, call.key, tmp, meta)
        finally:
            await asyncio.to_thread(tmp.unlink, True)
        cost = result.cost_usd if result.cost_usd is not None else call.spec.price.estimate()
        return Produced(path, cost, fresh=True)

    async def _call_provider(self, call: PaidCall, ref: StepRef) -> GenerationResult:
        submitted: list[str] = []

        async def on_submitted(remote_id: str) -> None:
            submitted.append(remote_id)
            await self._tracker.remote_id_saved(ref, remote_id)

        resume = await self._tracker.remote_id(ref)
        ctx = RunContext(timeout_s=call.spec.timeouts.total_s, on_submitted=on_submitted,
                         resume_remote_id=resume)  # fmt: skip
        try:
            return await call.produce(ctx)
        except asyncio.CancelledError:
            remote_id = submitted[-1] if submitted else resume
            if remote_id is not None:
                await _cancel_quietly(call.cancel, remote_id)
            raise
        except ProviderError:
            await self._tracker.remote_id_saved(ref, None)  # próxima tentativa cria outra
            raise


async def _cancel_quietly(cancel: Cancel, remote_id: str) -> None:
    with contextlib.suppress(Exception):
        await asyncio.shield(asyncio.wait_for(cancel(remote_id), CANCEL_TIMEOUT_S))
    logger.info("predição remota cancelada", extra={"remote_id": remote_id})
