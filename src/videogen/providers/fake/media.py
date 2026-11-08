"""Mídia sintética para os fakes: WAV em Python puro; MP4 via FFmpeg (lavfi)."""

import asyncio
import io
import math
import shutil
import struct
import wave
from pathlib import Path

from videogen.core.errors import MediaError

SAMPLE_RATE = 24_000


def sine_wav(duration_s: float, *, frequency: float = 220.0, rate: int = SAMPLE_RATE) -> bytes:
    """Tom senoidal mono 16-bit: áudio válido para ffprobe/loudnorm, sem dependências."""
    frames = int(duration_s * rate)
    amplitude = 0.3 * 32767
    samples = (int(amplitude * math.sin(2 * math.pi * frequency * i / rate)) for i in range(frames))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return buffer.getvalue()


async def render_test_pattern(
    dest: Path, *, duration_s: float, size: tuple[int, int], fps: int
) -> None:
    """MP4 H.264 com padrão de teste (`testsrc2`). Exige ffmpeg no PATH."""
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise MediaError("ffmpeg não encontrado: o FakeVideo precisa dele para gerar MP4")
    width, height = size
    args = [
        binary, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}:duration={duration_s}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(dest),
    ]  # fmt: skip
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise MediaError(f"ffmpeg falhou ao gerar vídeo fake: {stderr.decode()[-300:]}")
