"""Monta o `input` de cada modelo a partir do mapeamento declarado no YAML (`fields`).

Os nomes reais dos campos variam por modelo e não ficam no código: `fields` traduz o campo
lógico (text, ref_audio, prompt, seed...) para o nome do provedor. Campo lógico sem
mapeamento é simplesmente omitido (o modelo não o suporta).
"""

import base64
from typing import Any

from videogen.core.errors import ProviderError
from videogen.domain.catalog import ModelSpec
from videogen.domain.generation import JsonScalar, TTSRequest, VideoRequest

MAX_DATA_URI_BYTES = 1_000_000  # Replicate aceita data URIs pequenas (docs: < 1 MB)


def build_input(spec: ModelSpec, values: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = dict(spec.defaults)
    for logical, value in values.items():
        remote = spec.fields.get(logical)
        if remote is not None and value is not None:
            payload[remote] = value
    return payload


def aspect_ratio(width: int, height: int) -> str:
    return "9:16" if height > width else "16:9"


def tts_values(request: TTSRequest, ref_audio: bytes) -> dict[str, Any]:
    return {
        "text": request.text,
        "ref_audio": audio_data_uri(ref_audio),
        "ref_text": request.ref_text,
        "speed": request.speed,
        "language": request.language,
    }


def video_values(request: VideoRequest) -> dict[str, JsonScalar]:
    values: dict[str, JsonScalar] = {
        "prompt": request.prompt,
        "negative_prompt": request.negative_prompt or None,
        "width": request.width,
        "height": request.height,
        "aspect_ratio": aspect_ratio(request.width, request.height),
        "num_frames": request.num_frames,
        "fps": request.fps,
        "duration_s": round(request.num_frames / request.fps),
        "seed": request.seed,
    }
    return values | request.extra


def audio_data_uri(audio: bytes) -> str:
    if len(audio) > MAX_DATA_URI_BYTES:
        raise ProviderError(
            f"áudio de referência com {len(audio)} bytes excede {MAX_DATA_URI_BYTES} "
            "para envio inline; use uma referência mais curta"
        )
    return "data:audio/wav;base64," + base64.b64encode(audio).decode("ascii")
