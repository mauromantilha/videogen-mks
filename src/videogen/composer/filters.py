"""Filtergraph de vídeo de uma cena a partir do `SyncPlan` (função pura, testável sem FFmpeg).

Ordem: ajuste de tempo (setpts) → completar/aparar → fps constante → cobrir o quadro de saída
(scale + crop, sem distorcer) → zoom do freeze → legenda. O áudio é mapeado sem filtro.
"""

from dataclasses import dataclass

from videogen.domain.render_specs import ClipParams
from videogen.domain.sync import SyncPlan, SyncStrategy

ZOOM_STEP = 0.0006  # por quadro: ~1,8% por segundo a 30 fps
ZOOM_MAX = 1.12
VIDEO_LABEL = "v"


@dataclass(frozen=True)
class SubtitleRef:
    filename: str  # relativo ao cwd do ffmpeg: evita escapar ':' e '\' no filtro
    fonts_dir: str | None = None


def build_video_filter(
    plan: SyncPlan, params: ClipParams, *, t_video: float, subtitles: SubtitleRef | None
) -> str:
    steps = [*_timing(plan, t_video, params.fps), *_cover(params)]
    if plan.strategy is SyncStrategy.FREEZE_ZOOM:
        steps.append(_zoom(plan, params, t_video))
    if plan.strategy is SyncStrategy.TRIM:
        fade_start = max(0.0, plan.target_duration_s - params.sync.fade_out_s)
        steps += [
            f"trim=duration={plan.target_duration_s:.3f}",
            f"fade=t=out:st={fade_start:.3f}:d={params.sync.fade_out_s:.3f}",
        ]
    if subtitles is not None:
        steps.append(_ass(subtitles))
    return f"[0:v]{','.join(steps)}[{VIDEO_LABEL}]"


def _timing(plan: SyncPlan, t_video: float, fps: int) -> list[str]:
    steps: list[str] = []
    if plan.setpts_factor != 1.0:
        steps.append(f"setpts={plan.setpts_factor:.6f}*PTS")
    if plan.freeze_extra_s > 0:
        steps.append(f"tpad=stop_mode=clone:stop_duration={plan.freeze_extra_s:.3f}")
    steps.append(f"fps={fps}")
    return steps


def _cover(params: ClipParams) -> list[str]:
    w, h = params.width, params.height
    return [
        f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={w}:{h}",
        "setsar=1",
    ]


def _zoom(plan: SyncPlan, params: ClipParams, t_video: float) -> str:
    freeze_frame = round(t_video * plan.setpts_factor * params.fps)
    zoom = f"if(gte(on\\,{freeze_frame})\\,min(zoom+{ZOOM_STEP}\\,{ZOOM_MAX})\\,1)"
    return (
        f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s={params.width}x{params.height}:fps={params.fps}"
    )


def _ass(subtitles: SubtitleRef) -> str:
    fonts = f":fontsdir={subtitles.fonts_dir}" if subtitles.fonts_dir else ""
    return f"ass=filename={subtitles.filename}{fonts}"
