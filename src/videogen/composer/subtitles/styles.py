"""Estilos de legenda por proporção, proporcionais à resolução (PlayRes = saída).

9:16 deixa a legenda acima da faixa inferior ocupada pela UI de Reels/TikTok/Shorts.
"""

from dataclasses import dataclass

from videogen.domain.script import AspectRatio

DEFAULT_FONT = "DejaVu Sans"  # presente em fonts-dejavu-core (Docker) e na maioria dos Linux


@dataclass(frozen=True)
class AssStyle:
    play_res_x: int
    play_res_y: int
    font_size: int
    margin_v: int
    margin_h: int
    outline: float
    shadow: float
    max_words: int
    max_chars: int
    font_name: str = DEFAULT_FONT
    primary_colour: str = "&H00FFFFFF"  # &HAABBGGRR: branco opaco
    outline_colour: str = "&H00000000"  # preto
    back_colour: str = "&H80000000"  # sombra semitransparente
    bold: bool = True
    alignment: int = 2  # inferior central


# (fonte, margem vertical) como fração da altura; limites de linha por proporção
_PRESETS: dict[AspectRatio, tuple[float, float, int, int]] = {
    "9:16": (0.050, 0.20, 4, 28),
    "16:9": (0.064, 0.07, 6, 42),
}


def style_for(aspect_ratio: AspectRatio, width: int, height: int) -> AssStyle:
    font_ratio, margin_ratio, max_words, max_chars = _PRESETS[aspect_ratio]
    font_size = max(12, round(height * font_ratio))
    return AssStyle(
        play_res_x=width,
        play_res_y=height,
        font_size=font_size,
        margin_v=round(height * margin_ratio),
        margin_h=round(width * 0.06),
        outline=max(1.0, round(font_size / 16, 1)),
        shadow=1.0,
        max_words=max_words,
        max_chars=max_chars,
    )
