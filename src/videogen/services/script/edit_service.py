"""Edição manual do roteiro (RF-07): nunca chama LLM nem GPU.

Cada operação é uma transformação pura `roteiro -> roteiro` aplicada atomicamente, com
controle de versão otimista (`expected_version`). Erros de estrutura são recusados (422);
violações de regra (ex.: 13 palavras) são salvas e devolvidas como aviso por cena — quem
bloqueia é a aprovação. Assim um editor com salvamento automático não perde o que foi digitado.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from videogen.core.errors import ValidationFailed, VersionConflict
from videogen.domain.events import ScriptUpdated
from videogen.domain.freeze import effective_seed
from videogen.domain.job import JobState
from videogen.domain.script import MAX_SEED, SceneSpec, VideoScriptSchema
from videogen.domain.script_rules import RuleViolation, validate_rules
from videogen.domain.status import JobStatus
from videogen.ports.events import EventBus
from videogen.ports.history import ScriptHistory
from videogen.ports.repository import JobRepository

Transform = Callable[[VideoScriptSchema], VideoScriptSchema]
EDITABLE_FIELDS = frozenset({"texto_narrado", "prompt_video", "seed"})


@dataclass(frozen=True)
class EditResult:
    state: JobState
    violations: list[RuleViolation]


class ScriptEditService:
    def __init__(self, repo: JobRepository, bus: EventBus, history: ScriptHistory) -> None:
        self._repo = repo
        self._bus = bus
        self._history = history

    async def replace_script(
        self, job_id: str, script: VideoScriptSchema, expected_version: int
    ) -> EditResult:
        return await self._apply(job_id, expected_version, lambda _: script)

    async def patch_scene(
        self, job_id: str, index: int, fields: dict[str, Any], expected_version: int
    ) -> EditResult:
        unknown = set(fields) - EDITABLE_FIELDS
        if unknown:
            raise ValidationFailed(f"campos não editáveis: {sorted(unknown)}")
        return await self._apply(job_id, expected_version, _patch(index, fields))

    async def add_scene(
        self, job_id: str, after_index: int, scene: dict[str, Any], expected_version: int
    ) -> EditResult:
        def transform(script: VideoScriptSchema) -> VideoScriptSchema:
            new = _validated_scene({"scene_index": 0, **scene})
            scenes = list(script.cenas)
            scenes.insert(_check_index(script, after_index) + 1, new)
            return script.with_scenes(scenes)

        return await self._apply(job_id, expected_version, transform)

    async def remove_scene(self, job_id: str, index: int, expected_version: int) -> EditResult:
        def transform(script: VideoScriptSchema) -> VideoScriptSchema:
            _check_index(script, index)
            return script.with_scenes([s for s in script.cenas if s.scene_index != index])

        return await self._apply(job_id, expected_version, transform)

    async def move_scene(
        self, job_id: str, source: int, target: int, expected_version: int
    ) -> EditResult:
        def transform(script: VideoScriptSchema) -> VideoScriptSchema:
            scenes = list(script.cenas)
            moved = scenes.pop(_check_index(script, source))
            scenes.insert(_check_index(script, target), moved)
            return script.with_scenes(scenes)

        return await self._apply(job_id, expected_version, transform)

    async def bump_seed(self, job_id: str, index: int, expected_version: int) -> EditResult:
        """ "Gerar outra versão" da cena: nova seed ⇒ novo hash ⇒ novo vídeo (só desta cena)."""

        def transform(script: VideoScriptSchema) -> VideoScriptSchema:
            scene = script.cenas[_check_index(script, index)]
            digest = hashlib.sha256(f"{job_id}:{index}:{effective_seed(job_id, scene)}".encode())
            return _patch(index, {"seed": int(digest.hexdigest()[:8], 16) % (MAX_SEED + 1)})(script)

        return await self._apply(job_id, expected_version, transform)

    async def _apply(self, job_id: str, expected_version: int, transform: Transform) -> EditResult:
        def mutate(state: JobState) -> None:
            state.ensure_status(JobStatus.AWAITING_APPROVAL)
            if state.script_version != expected_version:
                raise VersionConflict(
                    "o roteiro mudou desde que foi exibido",
                    current_version=state.script_version,
                    requested_version=expected_version,
                )
            new = _structural(transform, state.require_script())
            if new.aspect_ratio != state.request.aspect_ratio:
                raise ValidationFailed("a proporção do roteiro deve ser a mesma do job")
            state.script, state.script_version, state.error = new, state.script_version + 1, None

        state = await self._repo.update(job_id, mutate)
        script = state.require_script()
        await self._history.save(job_id, state.script_version, script)
        self._bus.publish(job_id, ScriptUpdated(script_version=state.script_version))
        return EditResult(state, validate_rules(script, state.request.script_limits()))


def _structural(transform: Transform, script: VideoScriptSchema) -> VideoScriptSchema:
    try:
        return transform(script)
    except ValidationError as exc:
        raise ValidationFailed(f"roteiro inválido: {exc.errors()[0]['msg']}") from exc


def _patch(index: int, fields: dict[str, Any]) -> Transform:
    def transform(script: VideoScriptSchema) -> VideoScriptSchema:
        scenes = list(script.cenas)
        position = _check_index(script, index)
        scenes[position] = _validated_scene(scenes[position].model_dump() | fields)
        return script.with_scenes(scenes)

    return transform


def _validated_scene(data: dict[str, Any]) -> SceneSpec:
    return SceneSpec.model_validate(data)


def _check_index(script: VideoScriptSchema, index: int) -> int:
    if not 0 <= index < len(script.cenas):
        raise ValidationFailed(f"cena {index} não existe (o roteiro tem {len(script.cenas)})")
    return index
