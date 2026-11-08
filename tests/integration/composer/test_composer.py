"""T-040…T-047 com FFmpeg real: as 4 estratégias de sync, loudness, legenda, zoom e concat."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.media_factory import FAST, PROBE, RUNNER, frame_hash, make_audio, make_video
from videogen.composer.concat import Concatenator, concat_listing
from videogen.composer.ffmpeg_runner import FfmpegRunner
from videogen.composer.healthcheck import ToolchainCheck
from videogen.composer.loudnorm import LoudnessNormalizer
from videogen.composer.media_composer import FfmpegMediaComposer
from videogen.composer.scene_composer import SceneComposer
from videogen.core.errors import MediaError
from videogen.domain.media import ArtifactKind
from videogen.domain.render_specs import ClipParams, ClipSpec, ConcatParams, LoudnessParams
from videogen.ports.composer import MediaComposer
from videogen.ports.probe import MediaProbe

pytestmark = pytest.mark.ffmpeg
FPS = 24


def _spec(tmp: Path, video: Path, audio: Path, name: str, **overrides: Any) -> ClipSpec:
    params: dict[str, Any] = {
        "texto": "Proteja o seu futuro hoje mesmo.",
        "aspect_ratio": "9:16",
        "width": 180,
        "height": 320,
        "fps": FPS,
    }
    return ClipSpec(
        params=ClipParams.model_validate(params | overrides),
        video_path=video,
        audio_path=audio,
        out_path=tmp / f"{name}.mp4",
    )


@pytest.fixture
async def video(tmp_path: Path) -> Path:
    return await make_video(tmp_path / "raw.mp4", 2.0)


def test_portas_implementadas() -> None:
    assert isinstance(PROBE, MediaProbe)
    composer = FfmpegMediaComposer(
        LoudnessNormalizer(RUNNER), SceneComposer(RUNNER, PROBE), Concatenator(RUNNER, PROBE)
    )
    assert isinstance(composer, MediaComposer)


async def test_runner_sem_shell_erro_e_timeout(tmp_path: Path) -> None:
    hostile = tmp_path / "x; touch pwned"
    with pytest.raises(MediaError, match="ffmpeg falhou"):
        await RUNNER.ffmpeg(["-loglevel", "error", "-i", str(hostile), str(tmp_path / "o.mp4")])
    assert not (tmp_path / "pwned").exists() and not Path("pwned").exists()
    with pytest.raises(MediaError, match="não encontrado"):
        await FfmpegRunner(ffmpeg="ffmpeg-inexistente").ffmpeg(["-version"])
    slow = FfmpegRunner(timeout_s=0.5)
    with pytest.raises(MediaError, match="excedeu"):
        await slow.ffmpeg(["-f", "lavfi", "-i", "anullsrc", "-f", "null", "-"])


async def test_probe_e_validacao(tmp_path: Path, video: Path) -> None:
    info = await PROBE.validate(video, ArtifactKind.VIDEO_RAW)
    assert (info.duration_s, info.fps, info.width, info.video_codec) == (2.0, 16.0, 160, "h264")
    audio = await make_audio(tmp_path / "a.wav", 1.5)
    assert (await PROBE.probe(audio)).sample_rate == 24000
    with pytest.raises(MediaError, match="esperado vídeo"):
        await PROBE.validate(audio, ArtifactKind.VIDEO_RAW)
    (tmp_path / "vazio.mp4").touch()
    with pytest.raises(MediaError, match="vazia"):
        await PROBE.probe(tmp_path / "vazio.mp4")


async def test_loudnorm_atinge_menos_14_lufs(tmp_path: Path) -> None:
    normalizer, params = LoudnessNormalizer(RUNNER), LoudnessParams()
    quiet = await make_audio(tmp_path / "baixo.wav", 3.0, volume_db=-30)
    out = tmp_path / "norm.wav"
    await normalizer.normalize(quiet, out, params)
    assert (await normalizer.measure(quiet, params)).integrated < -30
    assert (await normalizer.measure(out, params)).integrated == pytest.approx(-14, abs=1)
    info = await PROBE.probe(out)
    assert (info.sample_rate, info.duration_s) == (48000, pytest.approx(3.0, abs=0.05))


async def test_loudnorm_de_silencio_nao_quebra(tmp_path: Path) -> None:
    silent = tmp_path / "silencio.wav"
    await RUNNER.ffmpeg(
        [
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            "1",
            str(silent),
        ]
    )
    await LoudnessNormalizer(RUNNER).normalize(silent, tmp_path / "o.wav", LoudnessParams())


@pytest.mark.parametrize("t_audio", [2.1, 2.5, 3.6, 1.2], ids=["none", "stretch", "freeze", "trim"])
async def test_clipe_dura_o_mesmo_que_a_fala(tmp_path: Path, video: Path, t_audio: float) -> None:
    audio = await make_audio(tmp_path / "a.wav", t_audio)
    out = await SceneComposer(RUNNER, PROBE, encoding=FAST).compose(
        _spec(tmp_path, video, audio, "c")
    )
    info = await PROBE.probe(out)
    assert info.duration_s == pytest.approx(t_audio, abs=2 / FPS)
    assert (info.width, info.height, info.fps, info.video_codec) == (180, 320, FPS, "h264")
    assert (info.audio_codec, info.sample_rate) == ("aac", 48000)
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []  # sem workdir


async def test_legenda_aparece_no_video(tmp_path: Path, video: Path) -> None:
    audio = await make_audio(tmp_path / "a.wav", 2.0)
    composer = SceneComposer(RUNNER, PROBE, encoding=FAST)
    with_subs = await composer.compose(_spec(tmp_path, video, audio, "com"))
    without = await composer.compose(_spec(tmp_path, video, audio, "sem", subtitles=False))
    assert await frame_hash(with_subs, 1.0) != await frame_hash(without, 1.0)


async def test_freeze_tem_zoom_suave_no_final(tmp_path: Path, video: Path) -> None:
    audio = await make_audio(tmp_path / "a.wav", 3.6)  # 2 s * 1,35 = 2,7 s; congela 0,9 s
    out = await SceneComposer(RUNNER, PROBE, encoding=FAST).compose(
        _spec(tmp_path, video, audio, "z", subtitles=False)
    )
    start, end = await asyncio.gather(frame_hash(out, 2.75), frame_hash(out, 3.5))
    assert start != end  # mesmo quadro congelado, mas com zoom crescente


async def test_concat_soma_duracoes_e_copia_video(tmp_path: Path, video: Path) -> None:
    composer = SceneComposer(RUNNER, PROBE, encoding=FAST)
    clips = []
    for index, seconds in enumerate((1.5, 2.0, 2.4)):
        audio = await make_audio(tmp_path / f"a{index}.wav", seconds)
        clips.append(await composer.compose(_spec(tmp_path, video, audio, f"c{index}")))
    final = await Concatenator(RUNNER, PROBE).concat(clips, tmp_path / "final.mp4", ConcatParams())
    info = await PROBE.validate(final, ArtifactKind.FINAL)
    assert info.duration_s == pytest.approx(5.9, abs=0.15)
    assert (info.width, info.audio_codec) == (180, "aac")


async def test_concat_com_perfis_diferentes_recodifica(tmp_path: Path, video: Path) -> None:
    composer = SceneComposer(RUNNER, PROBE, encoding=FAST)
    audio = await make_audio(tmp_path / "a.wav", 1.5)
    small = await composer.compose(_spec(tmp_path, video, audio, "p"))
    large = await composer.compose(_spec(tmp_path, video, audio, "g", width=360, height=640))
    final = await Concatenator(RUNNER, PROBE, FAST).concat(
        [small, large], tmp_path / "f.mp4", ConcatParams()
    )
    assert ((await PROBE.probe(final)).width, (await PROBE.probe(final)).height) == (180, 320)


def test_lista_do_concat_escapa_aspas(tmp_path: Path) -> None:
    listing = concat_listing([tmp_path / "it's.mp4"])
    assert listing == f"file '{tmp_path.resolve()}/it'\\''s.mp4'\n"


async def test_toolchain_local(tmp_path: Path) -> None:
    report = await ToolchainCheck(RUNNER).run()
    assert report.ok, report.problems
    broken = await ToolchainCheck(FfmpegRunner(ffmpeg="nao-existe")).run()
    assert not broken.ok
    missing_fonts = await ToolchainCheck(RUNNER, fonts_dir=tmp_path / "x").run()
    assert any("fontes" in p for p in missing_fonts.problems)
