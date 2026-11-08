"""Mídia sintética real (lavfi) para testes que exercitam o FFmpeg (composer, render, e2e)."""

import hashlib
from pathlib import Path

from videogen.composer.encoding import EncodeSettings
from videogen.composer.ffmpeg_runner import FfmpegRunner
from videogen.composer.probe import FfprobeProbe

RUNNER = FfmpegRunner(max_parallel=4)
PROBE = FfprobeProbe(RUNNER)
FAST = EncodeSettings(preset="ultrafast", crf=30)  # testes: velocidade > qualidade


async def make_video(path: Path, seconds: float, size: str = "160x288", rate: int = 16) -> Path:
    source = f"testsrc2=size={size}:rate={rate}:duration={seconds}"
    await RUNNER.ffmpeg(["-y", "-loglevel", "error", "-f", "lavfi", "-i", source,
                         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                         str(path)])  # fmt: skip
    return path


async def make_audio(path: Path, seconds: float, volume_db: int = -30) -> Path:
    source = f"sine=frequency=330:duration={seconds}"
    await RUNNER.ffmpeg(["-y", "-loglevel", "error", "-f", "lavfi", "-i", source,
                         "-af", f"volume={volume_db}dB", "-ar", "24000", "-ac", "1",
                         str(path)])  # fmt: skip
    return path


async def frame_hash(path: Path, at_s: float) -> str:
    """Hash dos pixels (cinza) de um quadro: compara quadros sem salvar imagens."""
    result = await RUNNER.ffmpeg(["-loglevel", "error", "-ss", f"{at_s:.3f}", "-i", str(path),
                                  "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray",
                                  "-"])  # fmt: skip
    return hashlib.sha256(result.stdout).hexdigest()
