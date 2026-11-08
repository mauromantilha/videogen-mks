"""Hash de conteúdo dos artefatos (RNF-02).

`job_id` e `scene_index` nunca entram: reordenar, clonar ou repetir uma cena reaproveita o
cache. Mudar o formato do payload exige subir `HASH_SCHEMA_VERSION` (testes com golden vectors).
"""

import hashlib
import json
from collections.abc import Mapping, Sequence

from videogen.domain.generation import TTSRequest, VideoRequest
from videogen.domain.media import ArtifactKind
from videogen.domain.render_specs import ClipParams, ConcatParams, LoudnessParams

HASH_SCHEMA_VERSION = 1


def content_hash(kind: ArtifactKind, payload: Mapping[str, object]) -> str:
    envelope = {"v": HASH_SCHEMA_VERSION, "kind": str(kind), "payload": payload}
    blob = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def audio_hash(request: TTSRequest) -> str:
    return content_hash(ArtifactKind.AUDIO_RAW, request.model_dump(mode="json"))


def video_hash(request: VideoRequest) -> str:
    return content_hash(ArtifactKind.VIDEO_RAW, request.model_dump(mode="json"))


def audio_norm_hash(raw_hash: str, params: LoudnessParams) -> str:
    payload = {"source": raw_hash, "params": params.model_dump(mode="json")}
    return content_hash(ArtifactKind.AUDIO_NORM, payload)


def clip_hash(audio_norm: str, video: str, params: ClipParams) -> str:
    payload = {"audio": audio_norm, "video": video, "params": params.model_dump(mode="json")}
    return content_hash(ArtifactKind.CLIP, payload)


def final_hash(clip_hashes: Sequence[str], params: ConcatParams) -> str:
    payload = {"clips": list(clip_hashes), "params": params.model_dump(mode="json")}
    return content_hash(ArtifactKind.FINAL, payload)
