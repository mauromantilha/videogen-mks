"""Execução de ffmpeg/ffprobe sem shell, com timeout e limite de paralelismo (RNF-11).

Argumentos sempre em lista (nada de `shell=True`): texto vindo do LLM nunca vira comando.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from videogen.core.errors import MediaError

STDERR_TAIL = 4096


@dataclass(frozen=True)
class RunResult:
    stdout: bytes
    stderr: str


class FfmpegRunner:
    def __init__(
        self,
        *,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        max_parallel: int = 2,
        timeout_s: float = 600,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._slots = asyncio.Semaphore(max_parallel)
        self._timeout_s = timeout_s

    async def ffmpeg(self, args: Sequence[str], *, cwd: Path | None = None) -> RunResult:
        """Codificação pesada: respeita `MAX_PARALLEL_FFMPEG`."""
        async with self._slots:
            return await self._run(self._ffmpeg, ["-nostdin", "-hide_banner", *args], cwd)

    async def ffprobe(self, args: Sequence[str]) -> RunResult:
        """Inspeção leve: não ocupa vaga de codificação."""
        return await self._run(self._ffprobe, ["-hide_banner", *args], None)

    async def _run(self, binary: str, args: Sequence[str], cwd: Path | None) -> RunResult:
        try:
            process = await asyncio.create_subprocess_exec(
                binary,
                *args,
                cwd=cwd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise MediaError(f"{binary} não encontrado no PATH") from exc
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), self._timeout_s)
        except TimeoutError as exc:
            await _kill(process)
            raise MediaError(f"{binary} excedeu {self._timeout_s:.0f}s") from exc
        except asyncio.CancelledError:
            await _kill(process)
            raise
        text = stderr.decode("utf-8", errors="replace")
        if process.returncode != 0:
            tail = text[-STDERR_TAIL:].strip()
            raise MediaError(
                f"{binary} falhou (código {process.returncode}): {tail[-500:]}", stderr_tail=tail
            )
        return RunResult(stdout=stdout, stderr=text)


async def _kill(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        process.kill()
        await process.wait()
