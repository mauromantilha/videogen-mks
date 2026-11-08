"""Serializa legendas em Advanced SubStation Alpha (.ass) para o filtro `ass` do FFmpeg.

O texto vem do LLM: chaves e barras invertidas são neutralizadas para que nenhuma
*override tag* (ex.: `{\\fs200}`) seja interpretada pelo libass.
"""

from collections.abc import Sequence

from videogen.composer.subtitles.chunker import TimedLine
from videogen.composer.subtitles.styles import AssStyle

_SANITIZE = str.maketrans({"{": "(", "}": ")", "\\": "/", "\n": " ", "\r": " "})
_STYLE_FIELDS = (
    "Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
    "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
_EVENT_FIELDS = "Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"


def sanitize(text: str) -> str:
    return " ".join(text.translate(_SANITIZE).split())


def ass_time(seconds: float) -> str:
    """H:MM:SS.cc (centésimos), o formato do ASS."""
    centiseconds = max(0, round(seconds * 100))
    hours, rest = divmod(centiseconds, 360_000)
    minutes, rest = divmod(rest, 6_000)
    secs, cents = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cents:02d}"


def render_ass(lines: Sequence[TimedLine], style: AssStyle) -> str:
    bold = -1 if style.bold else 0
    style_line = (
        f"Style: Default,{style.font_name},{style.font_size},{style.primary_colour},"
        f"&H000000FF,{style.outline_colour},{style.back_colour},{bold},0,0,0,100,100,0,0,1,"
        f"{style.outline},{style.shadow},{style.alignment},{style.margin_h},{style.margin_h},"
        f"{style.margin_v},1"
    )
    events = [
        f"Dialogue: 0,{ass_time(line.start_s)},{ass_time(line.end_s)},Default,,0,0,0,,"
        f"{sanitize(line.text)}"
        for line in lines
    ]
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {style.play_res_x}",
        f"PlayResY: {style.play_res_y}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]", f"Format: {_STYLE_FIELDS}", style_line, "",
        "[Events]", f"Format: {_EVENT_FIELDS}", *events, "",
    ])  # fmt: skip
