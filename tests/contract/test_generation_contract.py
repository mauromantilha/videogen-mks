"""Contrato de geração paga (TTS): Replicate (HTTP simulado) e FakeTTS no mesmo roteiro.

Prova as garantias de que o CachedStep (M7) depende: `on_submitted` antes do poll,
retomada sem reenvio, reenvio em falha transitória e nenhum reenvio em conteúdo recusado.
"""

from pathlib import Path

import httpx
import pytest
import respx

from tests.fakes.net import FAST_POLICY, Sleeper
from tests.unit.domain.test_request_generation import make_tts
from videogen.core.errors import ContentRejected, ProviderTimeout
from videogen.domain.catalog import ModelSpec
from videogen.domain.generation import RunContext
from videogen.ports.tts import TTSProvider
from videogen.providers.fake.behavior import FakeBehavior
from videogen.providers.fake.origin import FakeMediaOrigin
from videogen.providers.fake.tts import FakeTTS
from videogen.providers.http.client import ResilientHttpClient
from videogen.providers.replicate.client import API, ReplicateClient
from videogen.providers.replicate.runner import PredictionRunner
from videogen.providers.replicate.tts import ReplicateTTS

SPEC = ModelSpec(
    key="f5",
    kind="tts",
    provider="replicate",
    remote_ref="x-lance/f5-tts",
    version="v" * 64,
    fields={"text": "gen_text", "ref_audio": "ref_audio"},
    price={"unit": "per_second", "usd": 0.001},  # type: ignore[arg-type]
    allowed_hosts=("replicate.delivery",),
)
OUTPUT = "https://replicate.delivery/out.wav"
MARKER = "Proteja"  # aparece no texto do make_tts()


class ReplicateHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.router = respx.mock(assert_all_called=False)
        self.creates = 0
        self.statuses: list[dict[str, object]] = []
        sleeper = Sleeper()
        http = ResilientHttpClient(
            httpx.AsyncClient(), FAST_POLICY, provider="replicate", sleep=sleeper
        )
        runner = PredictionRunner(ReplicateClient(http, sleeper.schedule()))
        self.provider: TTSProvider = ReplicateTTS(runner, SPEC)
        self.ref = tmp_path / "ref.wav"
        self.ref.write_bytes(b"RIFF")
        self.cancels = self.router.post(url__regex=rf"{API}/predictions/.+/cancel").respond(
            200, json={}
        )
        self.router.post(f"{API}/predictions").mock(side_effect=self._create)
        self.router.get(url__regex=rf"{API}/predictions/[^/]+$").mock(side_effect=self._get)

    def _create(self, request: httpx.Request) -> httpx.Response:
        self.creates += 1
        return httpx.Response(201, json={"id": f"p{self.creates}", "status": "starting"})

    def _get(self, request: httpx.Request) -> httpx.Response:
        prediction_id = request.url.path.rsplit("/", 1)[-1]
        state = self.statuses.pop(0) if self.statuses else {"status": "processing"}
        return httpx.Response(200, json={"id": prediction_id, **state})

    def succeed_after(self, polls: int = 1) -> None:
        self.statuses += [{"status": "processing"}] * polls
        self.statuses.append(
            {"status": "succeeded", "output": OUTPUT, "metrics": {"predict_time": 4.0}}
        )

    def fail_transient_once(self) -> None:
        self.statuses.append({"status": "failed", "error": "E1001: CUDA out of memory"})

    def reject_content(self) -> None:
        self.statuses.append({"status": "failed", "error": "NSFW content detected"})

    def submit_count(self) -> int:
        return self.creates


class FakeHarness:
    def __init__(self, tmp_path: Path) -> None:
        self.behavior = FakeBehavior()
        self.provider: TTSProvider = FakeTTS(FakeMediaOrigin(tmp_path / "origin"), self.behavior)
        self.ref = tmp_path / "ref.wav"

    def succeed_after(self, polls: int = 1) -> None:
        pass

    def fail_transient_once(self) -> None:
        self.behavior.fail_when(MARKER, times=1)

    def reject_content(self) -> None:
        self.behavior.reject_when(MARKER)

    def submit_count(self) -> int:
        return len(self.behavior.submits)


Harness = ReplicateHarness | FakeHarness


@pytest.fixture(params=["replicate", "fake"])
def harness(request: pytest.FixtureRequest, tmp_path: Path) -> Harness:
    if request.param == "replicate":
        built = ReplicateHarness(tmp_path)
        built.router.start()
        request.addfinalizer(built.router.stop)
        return built
    return FakeHarness(tmp_path)


def _ctx(submitted: list[str], resume: str | None = None, timeout_s: float = 300) -> RunContext:
    async def on_submitted(remote_id: str) -> None:
        submitted.append(remote_id)

    return RunContext(timeout_s=timeout_s, on_submitted=on_submitted, resume_remote_id=resume)


async def _synthesize(harness: Harness, ctx: RunContext) -> str:
    result = await harness.provider.synthesize(make_tts(ref_audio_path=harness.ref), ctx)
    assert result.remote_id
    return result.output_url


async def test_sucesso_avisa_o_remote_id_uma_vez(harness: Harness) -> None:
    harness.succeed_after(polls=2)
    submitted: list[str] = []
    assert (await _synthesize(harness, _ctx(submitted))).startswith("https://")
    assert len(submitted) == 1 and harness.submit_count() == 1


async def test_retomada_nao_reenvia(harness: Harness) -> None:
    harness.succeed_after()
    submitted: list[str] = []
    await _synthesize(harness, _ctx(submitted, resume="p-anterior"))
    assert submitted == [] and harness.submit_count() == 0


async def test_falha_transitoria_reenvia_e_avisa_o_novo_id(harness: Harness) -> None:
    harness.fail_transient_once()
    harness.succeed_after()
    submitted: list[str] = []
    await _synthesize(harness, _ctx(submitted))
    assert len(submitted) == 2 and len(set(submitted)) == 2
    assert harness.submit_count() == 2


async def test_conteudo_recusado_nao_e_repetido(harness: Harness) -> None:
    harness.reject_content()
    with pytest.raises(ContentRejected):
        await _synthesize(harness, _ctx([]))
    assert harness.submit_count() <= 1


async def test_replicate_timeout_cancela_a_predicao(tmp_path: Path) -> None:
    harness = ReplicateHarness(tmp_path)
    with harness.router:
        with pytest.raises(ProviderTimeout):
            await _synthesize(harness, _ctx([], timeout_s=10))  # nunca sai de "processing"
        assert harness.cancels.call_count == 1


async def test_replicate_custo_por_segundo_de_gpu(tmp_path: Path) -> None:
    harness = ReplicateHarness(tmp_path)
    harness.succeed_after(polls=0)
    with harness.router:
        result = await harness.provider.synthesize(make_tts(ref_audio_path=harness.ref), _ctx([]))
    assert (result.cost_usd, result.provider_seconds) == (pytest.approx(0.004), 4.0)
