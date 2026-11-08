"""T-036: mídia sintética, origem fake (também Downloader) e adapter de vídeo do Replicate."""

import io
import json
import wave
from pathlib import Path

import httpx
import pytest
import respx

from tests.fakes.net import FAST_POLICY, Sleeper
from tests.unit.domain.test_request_generation import make_tts, make_video
from videogen.core.errors import ProviderError
from videogen.domain.catalog import ModelSpec
from videogen.domain.generation import RunContext
from videogen.ports.downloader import Downloader
from videogen.ports.video import VideoProvider
from videogen.providers.fake.behavior import FakeBehavior
from videogen.providers.fake.media import sine_wav
from videogen.providers.fake.origin import FAKE_HOST, FakeMediaOrigin
from videogen.providers.fake.tts import FakeTTS
from videogen.providers.fake.video import FakeVideo
from videogen.providers.http.client import ResilientHttpClient
from videogen.providers.replicate.client import API, ReplicateClient
from videogen.providers.replicate.runner import PredictionRunner
from videogen.providers.replicate.video import ReplicateVideo


async def _noop(_: str) -> None:
    return None


CTX = RunContext(timeout_s=60, on_submitted=_noop)


def test_wav_senoidal_tem_duracao_e_formato_corretos() -> None:
    with wave.open(io.BytesIO(sine_wav(2.5)), "rb") as handle:
        assert (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) == (
            1,
            2,
            24000,
        )
        assert handle.getnframes() / handle.getframerate() == pytest.approx(2.5)


async def test_tts_fake_dura_conforme_o_texto_e_e_baixavel(tmp_path: Path) -> None:
    origin = FakeMediaOrigin(tmp_path / "origin")
    assert isinstance(origin, Downloader)
    tts = FakeTTS(origin, FakeBehavior())
    text = "um dois três quatro cinco seis sete oito nove dez"
    result = await tts.synthesize(make_tts(text=text, ref_audio_path=tmp_path), CTX)
    assert result.output_url == f"https://{FAKE_HOST}/fake-tts-1.wav"

    dest = tmp_path / "baixado.wav"
    await origin.fetch(result.output_url, dest, allowed_hosts=[FAKE_HOST], max_bytes=10**7)
    with wave.open(str(dest), "rb") as handle:
        assert handle.getnframes() / handle.getframerate() == pytest.approx(4.0)  # 10 / 2.5
    with pytest.raises(ProviderError):
        await origin.fetch("https://evil.com/fake-tts-1.wav", dest, allowed_hosts=[], max_bytes=1)


@pytest.mark.ffmpeg
async def test_video_fake_gera_mp4_com_a_duracao_do_modelo(tmp_path: Path) -> None:
    origin = FakeMediaOrigin(tmp_path)
    video: VideoProvider = FakeVideo(origin, FakeBehavior())
    result = await video.generate(make_video(num_frames=32, fps=16, width=160, height=288), CTX)
    path = origin.path_for(Path(result.output_url).name)
    assert path.stat().st_size > 0 and path.read_bytes()[4:8] == b"ftyp"


@respx.mock
async def test_replicate_video_envia_versao_e_campos_mapeados() -> None:
    spec = ModelSpec(
        key="wan",
        kind="t2v",
        provider="replicate",
        remote_ref="o/wan",
        version="v" * 64,
        fields={"prompt": "prompt", "seed": "seed"},
        price={"unit": "per_run", "usd": 0.09},  # type: ignore[arg-type]
        allowed_hosts=("replicate.delivery",),
        limits={"fps": 16, "num_frames": 81, "sizes": {"9:16": [480, 832]}},
    )  # type: ignore[arg-type]
    create = respx.post(f"{API}/predictions").respond(201, json={"id": "p1", "status": "starting"})
    respx.get(f"{API}/predictions/p1").respond(
        200, json={"id": "p1", "status": "succeeded", "output": "https://replicate.delivery/v.mp4"}
    )
    sleeper = Sleeper()
    http = ResilientHttpClient(
        httpx.AsyncClient(), FAST_POLICY, provider="replicate", sleep=sleeper
    )
    video = ReplicateVideo(PredictionRunner(ReplicateClient(http, sleeper.schedule())), spec)

    result = await video.generate(make_video(), CTX)

    assert json.loads(create.calls.last.request.content) == {
        "version": "v" * 64,
        "input": {"prompt": "A woman smiles at her phone", "seed": 42},
    }
    assert (result.output_url, result.cost_usd) == ("https://replicate.delivery/v.mp4", 0.09)


@respx.mock
async def test_modelo_oficial_sem_versao_usa_endpoint_do_modelo() -> None:
    route = respx.post(f"{API}/models/dono/modelo/predictions").respond(
        201, json={"id": "p9", "status": "starting"}
    )
    http = ResilientHttpClient(httpx.AsyncClient(), FAST_POLICY, provider="replicate")
    created = await ReplicateClient(http).create("dono/modelo", None, {"prompt": "x"})
    assert created.id == "p9"
    assert json.loads(route.calls.last.request.content) == {"input": {"prompt": "x"}}
