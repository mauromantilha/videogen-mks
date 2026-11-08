"""T-070…T-072 (unitários): single-flight, limitador, tracker com orçamento e CachedStep."""

import asyncio
from pathlib import Path

import pytest

from tests.fakes.builders import JOB_ID, make_job
from tests.fakes.fake_clock import FakeClock
from tests.fakes.memory_cache import InMemoryArtifactCache
from tests.fakes.memory_repository import InMemoryJobRepository
from tests.fakes.recording_bus import RecordingEventBus
from tests.fakes.stage1 import CATALOG
from videogen.core.errors import BudgetExceeded, ProviderError
from videogen.domain.generation import GenerationResult, RunContext
from videogen.domain.media import ArtifactKind, MediaInfo
from videogen.domain.render_plan import output_size
from videogen.domain.status import JobStatus
from videogen.providers.fake.origin import FakeMediaOrigin
from videogen.services.render.cached_step import CachedStep, Cancel, PaidCall, Produce
from videogen.services.render.limiter import ProviderLimiter
from videogen.services.render.single_flight import SingleFlight
from videogen.services.render.step_tracker import StepRef, StepTracker

KEY = "a" * 64
REF = StepRef(JOB_ID, 0, "video")
SPEC = CATALOG.get("wan-2.1-t2v-480p", "t2v")
Tracked = tuple[InMemoryJobRepository, RecordingEventBus, StepTracker]
StepKit = tuple[CachedStep, FakeMediaOrigin, InMemoryArtifactCache]


@pytest.mark.parametrize(
    ("aspect", "resolution", "size"), [("9:16", "480p", (480, 854)), ("16:9", "720p", (1280, 720))]
)
def test_tamanho_de_saida(aspect: str, resolution: str, size: tuple[int, int]) -> None:
    assert output_size(aspect, resolution) == size  # type: ignore[arg-type]


async def test_single_flight_compartilha_valor_e_erro() -> None:
    flight, calls = SingleFlight(), []

    async def work() -> int:
        calls.append(1)
        await asyncio.sleep(0.01)
        return 7

    assert await asyncio.gather(*(flight.run("k", work) for _ in range(10))) == [7] * 10
    assert len(calls) == 1 and not flight.is_inflight("k")

    async def boom() -> int:
        await asyncio.sleep(0.01)
        raise ProviderError("x")

    results = await asyncio.gather(
        *(flight.run("e", boom) for _ in range(3)), return_exceptions=True
    )
    assert all(isinstance(r, ProviderError) for r in results)


async def test_limitador_usa_o_menor_teto() -> None:
    limiter, active, peak = ProviderLimiter({"t2v": 2}), [0], [0]

    async def job() -> None:
        async with limiter.slot("wan", "t2v", concurrency=8):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            await asyncio.sleep(0.01)
            active[0] -= 1

    await asyncio.gather(*(job() for _ in range(6)))
    assert peak[0] == 2


@pytest.fixture
async def tracked() -> Tracked:
    clock = FakeClock()
    repo, bus = InMemoryJobRepository(clock), RecordingEventBus(clock)
    await repo.create(make_job(JobStatus.RENDERING, n=2))
    return repo, bus, StepTracker(repo, bus)


async def test_tracker_contabiliza_custo_e_bloqueia_ao_estourar(tracked: Tracked) -> None:
    repo, bus, tracker = tracked
    await tracker.started(REF, paid=True)
    await tracker.done(REF, KEY, cost_usd=1.5, kind="video")
    job = await repo.get(JOB_ID)
    assert (job.ledger.video_usd, job.scenes[0].video.status) == (1.5, "done")
    assert bus.types(JOB_ID) == ["scene.step", "scene.step", "job.cost"]
    await tracker.done(StepRef(JOB_ID, 1, "audio"), KEY, cost_usd=0.6, kind="tts")  # 2.1 > 2.0
    with pytest.raises(BudgetExceeded):
        await tracker.started(StepRef(JOB_ID, 1, "video"), paid=True)
    await tracker.started(StepRef(JOB_ID, 1, "clip"), paid=False)  # compor não custa
    assert (await repo.get(JOB_ID)).scenes[1].video.status == "pending"


class AcceptingProbe:
    async def probe(self, path: Path) -> MediaInfo:
        return MediaInfo(duration_s=1.0, has_video=True, has_audio=True)

    async def validate(self, path: Path, kind: ArtifactKind) -> MediaInfo:
        return await self.probe(path)


def _step(
    tmp_path: Path, tracker: StepTracker
) -> tuple[CachedStep, FakeMediaOrigin, InMemoryArtifactCache]:
    origin, cache = FakeMediaOrigin(tmp_path / "o"), InMemoryArtifactCache(tmp_path / "c")
    return CachedStep(cache, origin, AcceptingProbe(), tracker, SingleFlight()), origin, cache


async def _no_cancel(remote_id: str) -> None:
    return None


def _call(produce: Produce, cancel: Cancel = _no_cancel) -> PaidCall:
    return PaidCall(ArtifactKind.VIDEO_RAW, KEY, SPEC, produce, cancel)


async def test_cached_step_baixa_valida_e_grava(tmp_path: Path, tracked: Tracked) -> None:
    repo, _, tracker = tracked
    step, origin, cache = _step(tmp_path, tracker)

    async def produce(ctx: RunContext) -> GenerationResult:
        await ctx.on_submitted("p1")
        return GenerationResult(
            remote_id="p1", output_url=origin.publish("p1.mp4", b"mp4"), cost_usd=0.09
        )

    produced = await step.fetch(_call(produce), REF)
    assert (produced.fresh, produced.cost_usd, produced.path.read_bytes()) == (True, 0.09, b"mp4")
    assert (await repo.get(JOB_ID)).scenes[0].video.remote_id == "p1"
    again = await step.fetch(_call(produce), REF)
    assert (again.fresh, again.cost_usd) == (False, 0.0)
    assert cache.meta[(ArtifactKind.VIDEO_RAW, KEY)]["remote_id"] == "p1"


async def test_falha_do_provedor_limpa_remote_id_e_do_download_mantem(
    tmp_path: Path, tracked: tuple
) -> None:  # type: ignore[type-arg]
    repo, _, tracker = tracked
    step, _, _ = _step(tmp_path, tracker)

    async def provider_fails(ctx: RunContext) -> GenerationResult:
        await ctx.on_submitted("p-falha")
        raise ProviderError("failed")

    async def download_fails(ctx: RunContext) -> GenerationResult:
        await ctx.on_submitted("p-pago")
        return GenerationResult(remote_id="p-pago", output_url="https://fake.videogen.local/sumiu")

    with pytest.raises(ProviderError):
        await step.fetch(_call(provider_fails), REF)
    assert (await repo.get(JOB_ID)).scenes[0].video.remote_id is None
    with pytest.raises(ProviderError):
        await step.fetch(_call(download_fails), REF)
    assert (await repo.get(JOB_ID)).scenes[0].video.remote_id == "p-pago"  # retry só baixa


async def test_cancelamento_cancela_a_predicao_remota(tmp_path: Path, tracked: Tracked) -> None:
    _, _, tracker = tracked
    step, _, _ = _step(tmp_path, tracker)
    canceled: list[str] = []

    async def hang(ctx: RunContext) -> GenerationResult:
        await ctx.on_submitted("p-longa")
        await asyncio.Event().wait()
        raise AssertionError

    async def cancel(remote_id: str) -> None:
        canceled.append(remote_id)

    task = asyncio.create_task(step.fetch(_call(hang, cancel), REF))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert canceled == ["p-longa"]
