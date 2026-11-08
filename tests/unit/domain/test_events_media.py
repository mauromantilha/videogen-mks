"""T-016: eventos (união discriminada, SSE) e tipos de mídia."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from tests.fakes.builders import VOICE_ID
from videogen.domain.events import Event, EventPayload, SceneStepChanged
from videogen.domain.media import MediaInfo, VoiceRef
from videogen.domain.progress import StepStatus

TS = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "expected_type"),
    [
        ({"type": "job.status", "status": "rendering"}, "job.status"),
        ({"type": "script.updated", "script_version": 3}, "script.updated"),
        ({"type": "scene.step", "scene_index": 1, "step": "video", "status": "done"}, "scene.step"),
        ({"type": "job.cost", "spent_usd": 0.1}, "job.cost"),
        ({"type": "job.completed", "final_hash": "f" * 64}, "job.completed"),
        ({"type": "job.failed", "error": {"code": "X", "message": "y"}}, "job.failed"),
    ],
)
def test_payload_e_escolhido_pelo_campo_type(raw: dict[str, object], expected_type: str) -> None:
    payload = TypeAdapter(EventPayload).validate_python(raw)
    assert payload.type == expected_type


def test_tipo_desconhecido_e_rejeitado() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(EventPayload).validate_python({"type": "job.exploded"})


def test_formato_sse() -> None:
    data = SceneStepChanged(scene_index=2, step="audio", status=StepStatus.DONE, cached=True)
    event = Event(seq=7, job_id="job_0123456789ab", ts=TS, data=data)

    lines = event.to_sse().split("\n")

    assert lines[:2] == ["id: 7", "event: scene.step"]
    assert json.loads(lines[2].removeprefix("data: "))["cached"] is True
    assert event.to_sse().endswith("\n\n")
    assert event.to_sse().count("\n") == 4  # data em uma linha só


def test_evento_sobrevive_ida_e_volta() -> None:
    data = SceneStepChanged(scene_index=0, step="clip", status=StepStatus.RUNNING)
    event = Event(seq=1, job_id="job_0123456789ab", ts=TS, data=data)
    assert Event.model_validate_json(event.model_dump_json()) == event


def test_media_info_e_voz() -> None:
    info = MediaInfo(duration_s=5.06, has_video=True, has_audio=False, fps=16.0)
    assert info.width is None
    voice = VoiceRef(
        voice_id=VOICE_ID,
        name="Mauro",
        ref_text="Olá.",
        sha256="a" * 64,
        duration_s=6.2,
        path=Path("ref.wav"),
        created_at=TS,
    )
    assert voice.voice_id == VOICE_ID
    with pytest.raises(ValidationError):
        VoiceRef.model_validate(voice.model_dump() | {"voice_id": "../x"})
