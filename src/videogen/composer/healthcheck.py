"""Verifica o toolchain no startup e no `/readyz` (RNF-13): sem ele não há render."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from videogen.composer.ffmpeg_runner import FfmpegRunner
from videogen.core.errors import MediaError

MIN_MAJOR_VERSION = 6
_VERSION = re.compile(r"version\s+n?(\d+)\.")
REQUIRED_FILTERS = ("ass", "loudnorm", "zoompan", "tpad")


@dataclass(frozen=True)
class ToolchainReport:
    version: str | None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


class ToolchainCheck:
    def __init__(self, runner: FfmpegRunner, fonts_dir: Path | None = None) -> None:
        self._runner = runner
        self._fonts_dir = fonts_dir

    async def run(self) -> ToolchainReport:
        try:
            version_text = (await self._runner.ffmpeg(["-version"])).stdout.decode()
            filters = (await self._runner.ffmpeg(["-filters"])).stdout.decode()
            encoders = (await self._runner.ffmpeg(["-encoders"])).stdout.decode()
            await self._runner.ffprobe(["-version"])
        except MediaError as exc:
            return ToolchainReport(version=None, problems=[exc.message])
        match = _VERSION.search(version_text)
        problems = _version_problems(match)
        problems += [
            f"filtro ausente: {name} (FFmpeg compilado sem suporte?)"
            for name in REQUIRED_FILTERS
            if not re.search(rf"\s{name}\s", filters)
        ]
        if not re.search(r"\slibx264\s", encoders):
            problems.append("encoder libx264 ausente")
        if self._fonts_dir is not None and not self._fonts_dir.is_dir():
            problems.append(f"diretório de fontes inexistente: {self._fonts_dir}")
        return ToolchainReport(version=match.group(1) if match else None, problems=problems)


def _version_problems(match: re.Match[str] | None) -> list[str]:
    if match is None:
        return []  # builds de git ("N-12345-g...") não têm versão numérica: não bloqueia
    if int(match.group(1)) < MIN_MAJOR_VERSION:
        return [f"FFmpeg {match.group(1)} < {MIN_MAJOR_VERSION}"]
    return []
