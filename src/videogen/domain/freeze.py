"""Congelamento do roteiro na aprovação (RF-09): fixa seeds e cria o progresso por cena."""

import hashlib
from datetime import datetime

from videogen.core.errors import VersionConflict
from videogen.domain.job import Approval, JobState
from videogen.domain.progress import SceneProgress
from videogen.domain.script import MAX_SEED, SceneSpec
from videogen.domain.status import JobStatus


def derive_seed(job_id: str, scene_index: int) -> int:
    """Seed determinística: a estimativa e o render calculam o mesmo hash antes da aprovação."""
    digest = hashlib.sha256(f"{job_id}:{scene_index}".encode()).hexdigest()
    return int(digest[:8], 16) % (MAX_SEED + 1)


def effective_seed(job_id: str, scene: SceneSpec) -> int:
    return scene.seed if scene.seed is not None else derive_seed(job_id, scene.scene_index)


def freeze_for_render(
    state: JobState, *, script_version: int, max_budget_usd: float, now: datetime
) -> None:
    """Aprova a versão exibida ao usuário. Seeds já definidas nunca são sobrescritas."""
    state.ensure_status(JobStatus.AWAITING_APPROVAL)
    if script_version != state.script_version:
        raise VersionConflict(
            "o roteiro mudou desde que foi exibido",
            current_version=state.script_version,
            requested_version=script_version,
        )
    script = state.require_script()
    seeded = [
        scene.model_copy(update={"seed": effective_seed(state.job_id, scene)})
        for scene in script.cenas
    ]
    state.script = script.model_copy(update={"cenas": seeded})
    state.scenes = [SceneProgress(scene_index=scene.scene_index) for scene in seeded]
    state.approval = Approval(
        script_version=script_version, approved_at=now, max_budget_usd=max_budget_usd
    )
    state.final_hash = None
    state.transition_to(JobStatus.APPROVED)
