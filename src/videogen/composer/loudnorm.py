"""Normalização EBU R128 em duas passadas (RF-02: -14 LUFS ± 1 LU).

Passada 1 mede; passada 2 aplica com os valores medidos em modo linear (sem bombeamento).
Silêncio total não tem loudness mensurável: só é convertido para o formato de saída.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from videogen.composer.ffmpeg_runner import FfmpegRunner
from videogen.core.errors import MediaError
from videogen.domain.render_specs import LoudnessParams

# O FFmpeg imprime progresso depois do JSON: procura o último bloco com `input_i`.
_JSON_BLOCK = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


@dataclass(frozen=True)
class LoudnessMeasurement:
    integrated: float
    true_peak: float
    lra: float
    threshold: float
    offset: float

    @property
    def silent(self) -> bool:
        return self.integrated == float("-inf")


class LoudnessNormalizer:
    def __init__(self, runner: FfmpegRunner) -> None:
        self._runner = runner

    async def measure(self, src: Path, params: LoudnessParams) -> LoudnessMeasurement:
        target = _target(params)
        args = ["-i", str(src), "-af", f"{target}:print_format=json", "-f", "null", "-"]
        result = await self._runner.ffmpeg(args)
        return parse_measurement(result.stderr)

    async def normalize(self, src: Path, dst: Path, params: LoudnessParams) -> None:
        measured = await self.measure(src, params)
        audio_filter = (
            "anull"
            if measured.silent
            else (
                f"{_target(params)}:measured_I={measured.integrated}:"
                f"measured_TP={measured.true_peak}:measured_LRA={measured.lra}:"
                f"measured_thresh={measured.threshold}:offset={measured.offset}:linear=true"
            )
        )
        await self._runner.ffmpeg([
            "-y", "-loglevel", "error", "-i", str(src), "-af", audio_filter,
            "-ar", str(params.sample_rate), "-ac", "1", "-c:a", "pcm_s16le", str(dst),
        ])  # fmt: skip


def _target(params: LoudnessParams) -> str:
    return f"loudnorm=I={params.integrated_lufs}:TP={params.true_peak_db}:LRA={params.lra}"


def parse_measurement(stderr: str) -> LoudnessMeasurement:
    blocks = _JSON_BLOCK.findall(stderr)
    if not blocks:
        raise MediaError("loudnorm não devolveu a medição em JSON")
    data = json.loads(blocks[-1])
    try:
        return LoudnessMeasurement(
            integrated=float(data["input_i"]),
            true_peak=float(data["input_tp"]),
            lra=float(data["input_lra"]),
            threshold=float(data["input_thresh"]),
            offset=float(data["target_offset"]),
        )
    except (KeyError, ValueError) as exc:
        raise MediaError(f"medição de loudness incompleta: {exc}") from exc
