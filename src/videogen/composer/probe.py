"""ffprobe → MediaInfo. A duração medida é a fonte de verdade (nunca "81 frames")."""

import asyncio
import json
from pathlib import Path
from typing import Any

from videogen.composer.ffmpeg_runner import FfmpegRunner
from videogen.core.errors import MediaError
from videogen.domain.media import ArtifactKind, MediaInfo

_NEEDS_AUDIO = frozenset(
    {ArtifactKind.AUDIO_RAW, ArtifactKind.AUDIO_NORM, ArtifactKind.CLIP, ArtifactKind.FINAL}
)
_NEEDS_VIDEO = frozenset({ArtifactKind.VIDEO_RAW, ArtifactKind.CLIP, ArtifactKind.FINAL})


class FfprobeProbe:
    def __init__(self, runner: FfmpegRunner) -> None:
        self._runner = runner

    async def probe(self, path: Path) -> MediaInfo:
        if not await asyncio.to_thread(_non_empty, path):
            raise MediaError(f"mídia ausente ou vazia: {path.name}")
        args = ["-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
        result = await self._runner.ffprobe(args)
        return parse_probe(json.loads(result.stdout or b"{}"), path.name)

    async def validate(self, path: Path, kind: ArtifactKind) -> MediaInfo:
        info = await self.probe(path)
        if kind in _NEEDS_AUDIO and not info.has_audio:
            raise MediaError(f"{path.name}: esperado áudio ({kind})")
        if kind in _NEEDS_VIDEO and not info.has_video:
            raise MediaError(f"{path.name}: esperado vídeo ({kind})")
        if info.duration_s <= 0:
            raise MediaError(f"{path.name}: duração inválida")
        return info


def _non_empty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def parse_probe(data: dict[str, Any], name: str = "mídia") -> MediaInfo:
    streams: list[dict[str, Any]] = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None and audio is None:
        raise MediaError(f"{name}: nenhum fluxo de áudio ou vídeo")
    duration = _float((data.get("format") or {}).get("duration"))
    if duration is None:
        duration = max(_float(s.get("duration")) or 0.0 for s in streams)
    return MediaInfo(
        duration_s=duration,
        has_video=video is not None,
        has_audio=audio is not None,
        fps=_rate(video.get("avg_frame_rate")) if video else None,
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        video_codec=video.get("codec_name") if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
    )


def _float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _rate(value: object) -> float | None:
    if not isinstance(value, str) or "/" not in value:
        return None
    numerator, denominator = value.split("/", 1)
    return float(numerator) / float(denominator) if float(denominator) else None
