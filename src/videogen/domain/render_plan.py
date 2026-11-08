"""Pedidos de geração de uma cena — função única usada pela estimativa (M5) e pelo render (M7).

Se a estimativa e o render montassem os pedidos separadamente, os hashes poderiam divergir e
uma cena em cache seria cobrada de novo. Aqui há uma só definição.
"""

from videogen.core.errors import ValidationFailed
from videogen.domain.catalog import ModelSpec
from videogen.domain.freeze import effective_seed
from videogen.domain.generation import TTSRequest, VideoRequest
from videogen.domain.media import VoiceRef
from videogen.domain.script import AspectRatio, SceneSpec, VideoScriptSchema

DEFAULT_SPEED = 1.0


def compose_prompt(scene: SceneSpec, script: VideoScriptSchema) -> str:
    """Prompt da cena + âncora de estilo comum a todas as cenas (coerência visual)."""
    base = scene.prompt_video.rstrip(" .")
    return f"{base}. {script.estilo_visual}" if script.estilo_visual else base


def tts_request(scene: SceneSpec, spec: ModelSpec, voice: VoiceRef) -> TTSRequest:
    speed = spec.defaults.get("speed", DEFAULT_SPEED)
    return TTSRequest(
        model_key=spec.key,
        model_version=spec.model_version,
        text=scene.texto_narrado,
        ref_text=voice.ref_text,
        ref_audio_sha256=voice.sha256,
        speed=float(speed) if isinstance(speed, int | float) else DEFAULT_SPEED,
        ref_audio_path=voice.path,
    )


def video_request(
    job_id: str,
    scene: SceneSpec,
    script: VideoScriptSchema,
    spec: ModelSpec,
    aspect_ratio: AspectRatio,
) -> VideoRequest:
    if spec.limits is None:
        raise ValidationFailed(f"{spec.key} não declara limites de vídeo")
    width, height = spec.limits.size_for(aspect_ratio)
    return VideoRequest(
        model_key=spec.key,
        model_version=spec.model_version,
        prompt=compose_prompt(scene, script),
        width=width,
        height=height,
        num_frames=spec.limits.num_frames,
        fps=spec.limits.fps,
        seed=effective_seed(job_id, scene),
    )
