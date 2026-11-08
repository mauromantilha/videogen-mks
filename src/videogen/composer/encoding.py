"""Perfil de codificação único de todos os clipes: pré-condição do concat sem recodificar."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EncodeSettings:
    preset: str = "medium"
    crf: int = 20
    audio_bitrate_k: int = 192
    sample_rate: int = 48_000

    def video_args(self, fps: int) -> list[str]:
        return ["-c:v", "libx264", "-preset", self.preset, "-crf", str(self.crf),
                "-pix_fmt", "yuv420p", "-r", str(fps)]  # fmt: skip

    def audio_args(self) -> list[str]:
        return ["-c:a", "aac", "-b:a", f"{self.audio_bitrate_k}k",
                "-ar", str(self.sample_rate), "-ac", "2"]  # fmt: skip
