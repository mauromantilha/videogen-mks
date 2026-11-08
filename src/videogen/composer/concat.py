"""Concatenação final (RF-06). Vídeo copiado (perfil uniforme); só o áudio é recodificado,
o que elimina os estalos do *priming* do AAC nas emendas. Perfis divergentes (ex.: clipe de
uma versão antiga) caem no caminho lento: recodificar o vídeo no perfil do primeiro clipe.
"""

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

from videogen.composer.encoding import EncodeSettings
from videogen.composer.ffmpeg_runner import FfmpegRunner
from videogen.composer.probe import FfprobeProbe
from videogen.core.errors import MediaError
from videogen.domain.media import ArtifactKind, MediaInfo
from videogen.domain.render_specs import ConcatParams

logger = logging.getLogger(__name__)
TOLERANCE_PER_CLIP_S = 0.05


class Concatenator:
    def __init__(
        self, runner: FfmpegRunner, probe: FfprobeProbe, encoding: EncodeSettings | None = None
    ) -> None:
        self._runner = runner
        self._probe = probe
        self._encoding = encoding or EncodeSettings()

    async def concat(self, clips: Sequence[Path], dst: Path, params: ConcatParams) -> Path:
        if not clips:
            raise MediaError("nada para concatenar")
        infos = [await self._probe.validate(clip, ArtifactKind.CLIP) for clip in clips]
        listing = dst.with_name(f".{dst.name}.concat.txt")
        await asyncio.to_thread(listing.write_text, concat_listing(clips), "utf-8")
        try:
            await self._runner.ffmpeg(self._args(listing, dst, infos, params))
        finally:
            await asyncio.to_thread(listing.unlink, True)
        await self._check(dst, infos, len(clips))
        return dst

    def _args(
        self, listing: Path, dst: Path, infos: list[MediaInfo], params: ConcatParams
    ) -> list[str]:
        audio = ["-c:a", params.audio_codec, "-b:a", f"{params.audio_bitrate_k}k",
                 "-ar", str(params.sample_rate), "-ac", "2"]  # fmt: skip
        faststart = ["-movflags", "+faststart"] if params.faststart else []
        return ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                *self._video_args(infos), *audio, *faststart, str(dst)]  # fmt: skip

    def _video_args(self, infos: list[MediaInfo]) -> list[str]:
        first = infos[0]
        if all(_profile(info) == _profile(first) for info in infos):
            return ["-c:v", "copy"]
        logger.warning("clipes com perfis diferentes: recodificando o vídeo no concat")
        fps = round(first.fps or 30)
        cover = (
            f"scale={first.width}:{first.height}:force_original_aspect_ratio=increase,"
            f"crop={first.width}:{first.height},setsar=1,fps={fps}"
        )
        return ["-vf", cover, *self._encoding.video_args(fps)]

    async def _check(self, dst: Path, infos: list[MediaInfo], count: int) -> None:
        info = await self._probe.validate(dst, ArtifactKind.FINAL)
        expected = sum(item.duration_s for item in infos)
        if abs(info.duration_s - expected) > TOLERANCE_PER_CLIP_S * count:
            raise MediaError(f"final com {info.duration_s:.2f}s; esperado {expected:.2f}s")


def concat_listing(clips: Sequence[Path]) -> str:
    """Arquivo do concat demuxer; aspas simples no caminho viram `'\\''`."""
    escaped = (str(clip.resolve()).replace("'", "'\\''") for clip in clips)
    return "".join(f"file '{path}'\n" for path in escaped)


def _profile(info: MediaInfo) -> tuple[object, ...]:
    return (info.video_codec, info.width, info.height, round(info.fps or 0, 2))
