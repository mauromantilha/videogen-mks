"""Construtores de dados válidos para os testes (sobrescreva só o que importa ao teste)."""

from typing import Any

from tests.fakes.fake_clock import DEFAULT_START
from videogen.domain.freeze import freeze_for_render
from videogen.domain.job import JobState
from videogen.domain.progress import ErrorInfo
from videogen.domain.request import JobRequest
from videogen.domain.script import SceneSpec, VideoScriptSchema
from videogen.domain.status import JobStatus

JOB_ID = "job_0123456789ab"
VOICE_ID = "voz_0123456789ab"
NARRATION = "Imagine proteger o seu futuro com um clique."
PROMPT = "A young woman smiles at her phone in a sunlit apartment, warm light, slow dolly-in"
_RENDER_PATH = (JobStatus.RENDERING, JobStatus.FINALIZING, JobStatus.COMPLETED)


def make_request(**overrides: Any) -> JobRequest:
    data: dict[str, Any] = {
        "tema": "Seguro de vida para jovens profissionais",
        "n_cenas": 3,
        "models": {"llm": "deepseek-chat", "tts": "f5-tts", "video": "wan-2.1-t2v-480p"},
        "voice_id": VOICE_ID,
    }
    return JobRequest.model_validate(data | overrides)


def make_scene(index: int = 0, **overrides: Any) -> SceneSpec:
    data = {"scene_index": index, "texto_narrado": NARRATION, "prompt_video": PROMPT}
    return SceneSpec.model_validate(data | overrides)


def make_script(n: int = 3, **overrides: Any) -> VideoScriptSchema:
    data: dict[str, Any] = {
        "produto_tema": "Seguro de vida",
        "estilo_visual": "cinematic, warm light, shallow depth of field",
        "cenas": [make_scene(i).model_dump() for i in range(n)],
    }
    return VideoScriptSchema.model_validate(data | overrides)


def make_job(status: JobStatus = JobStatus.AWAITING_APPROVAL, n: int = 3) -> JobState:
    """Job no status pedido, construído só por transições legítimas."""
    state = JobState.new(JOB_ID, make_request(n_cenas=n), DEFAULT_START)
    if status is JobStatus.SCRIPTING:
        return state
    if status is JobStatus.FAILED:
        state.fail("scripting", ErrorInfo(code="PROVIDER_ERROR", message="falhou"))
        return state
    state.script, state.script_version = make_script(n), 1
    state.transition_to(JobStatus.AWAITING_APPROVAL)
    if status in (JobStatus.AWAITING_APPROVAL, JobStatus.CANCELED):
        if status is JobStatus.CANCELED:
            state.transition_to(JobStatus.CANCELED)
        return state
    freeze_for_render(state, script_version=1, max_budget_usd=2.0, now=DEFAULT_START)
    for target in _RENDER_PATH[: _RENDER_PATH.index(status) + 1] if status in _RENDER_PATH else ():
        state.transition_to(target)
    return JobState.model_validate(state.model_dump())
