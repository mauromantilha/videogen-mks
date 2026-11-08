"""Compõe o clipe de uma cena (RF-04, RF-05): probe → plan_sync → .ass → um único ffmpeg.

O FFmpeg roda com `cwd` num diretório de trabalho da cena, então a legenda é referenciada
por nome relativo. A saída é validada: duração = áudio (± 2 quadros) e perfil uniforme.
"""

import asyncio
import shutil
from pathlib import Path

from videogen.composer.encoding import EncodeSettings
from videogen.composer.ffmpeg_runner import FfmpegRunner
from videogen.composer.filters import VIDEO_LABEL, SubtitleRef, build_video_filter
from videogen.composer.probe import FfprobeProbe
from videogen.composer.subtitles.ass_writer import render_ass
from videogen.composer.subtitles.chunker import timed_lines
from videogen.composer.subtitles.styles import style_for
from videogen.core.errors import MediaError
from videogen.domain.media import ArtifactKind
from videogen.domain.render_specs import ClipSpec
from videogen.domain.sync import plan_sync

SUBTITLE_FILE = "scene.ass"
TOLERANCE_FRAMES = 2


class SceneComposer:
    def __init__(
        self,
        runner: FfmpegRunner,
        probe: FfprobeProbe,
        *,
        encoding: EncodeSettings | None = None,
        fonts_dir: Path | None = None,
    ) -> None:
        self._runner = runner
        self._probe = probe
        self._encoding = encoding or EncodeSettings()
        self._fonts_dir = fonts_dir

    async def compose(self, spec: ClipSpec) -> Path:
        video = await self._probe.validate(spec.video_path, ArtifactKind.VIDEO_RAW)
        audio = await self._probe.validate(spec.audio_path, ArtifactKind.AUDIO_NORM)
        plan = plan_sync(audio.duration_s, video.duration_s, spec.params.sync)
        workdir = spec.out_path.parent / f".{spec.out_path.name}.work"
        await asyncio.to_thread(workdir.mkdir, parents=True, exist_ok=True)
        try:
            subtitles = await self._write_subtitles(spec, workdir, audio.duration_s)
            graph = build_video_filter(
                plan, spec.params, t_video=video.duration_s, subtitles=subtitles
            )
            await self._runner.ffmpeg(self._args(spec, graph, plan.target_duration_s), cwd=workdir)
        finally:
            await asyncio.to_thread(shutil.rmtree, workdir, True)
        await self._check_output(spec, plan.target_duration_s)
        return spec.out_path

    async def _write_subtitles(
        self, spec: ClipSpec, workdir: Path, duration_s: float
    ) -> SubtitleRef | None:
        params = spec.params
        if not params.subtitles:
            return None
        style = style_for(params.aspect_ratio, params.width, params.height)
        lines = timed_lines(
            params.texto, duration_s, max_words=style.max_words, max_chars=style.max_chars
        )
        content = render_ass(lines, style)
        await asyncio.to_thread((workdir / SUBTITLE_FILE).write_text, content, "utf-8")
        fonts = str(self._fonts_dir.resolve()) if self._fonts_dir else None
        return SubtitleRef(filename=SUBTITLE_FILE, fonts_dir=fonts)

    def _args(self, spec: ClipSpec, graph: str, duration_s: float) -> list[str]:
        return [
            "-y", "-loglevel", "error",
            "-i", str(spec.video_path.resolve()), "-i", str(spec.audio_path.resolve()),
            "-filter_complex", graph, "-map", f"[{VIDEO_LABEL}]", "-map", "1:a",
            "-t", f"{duration_s:.3f}",
            *self._encoding.video_args(spec.params.fps), *self._encoding.audio_args(),
            "-movflags", "+faststart", str(spec.out_path.resolve()),
        ]  # fmt: skip

    async def _check_output(self, spec: ClipSpec, expected_s: float) -> None:
        info = await self._probe.validate(spec.out_path, ArtifactKind.CLIP)
        tolerance = TOLERANCE_FRAMES / spec.params.fps
        if abs(info.duration_s - expected_s) > tolerance:
            raise MediaError(
                f"clipe com {info.duration_s:.3f}s; esperado {expected_s:.3f}s ± {tolerance:.3f}s"
            )
        size = (info.width, info.height)
        if size != (spec.params.width, spec.params.height) or info.video_codec != "h264":
            raise MediaError(f"clipe fora do perfil: {size}, codec {info.video_codec}")
