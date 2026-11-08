"""Corpos e respostas das rotas de roteiro e aprovação."""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from videogen.domain.script import MAX_SEED, VideoScriptSchema
from videogen.domain.script_rules import RuleViolation

_STRICT = ConfigDict(extra="forbid")


class ViolationView(BaseModel):
    scene_index: int | None
    code: str
    message: str

    @classmethod
    def many(cls, violations: Sequence[RuleViolation]) -> list["ViolationView"]:
        return [cls(scene_index=v.scene_index, code=v.code, message=v.message) for v in violations]


class ScriptView(BaseModel):
    script_version: int
    script: VideoScriptSchema
    violations: list[ViolationView]


class EditResponse(BaseModel):
    script_version: int
    violations: list[ViolationView]


class VersionedBody(BaseModel):
    model_config = _STRICT
    expected_version: int = Field(ge=0)


class ReplaceScriptBody(VersionedBody):
    script: VideoScriptSchema


class PatchSceneBody(VersionedBody):
    texto_narrado: str | None = None
    prompt_video: str | None = None
    seed: int | None = Field(default=None, ge=0, le=MAX_SEED)

    def fields(self) -> dict[str, object]:
        return self.model_dump(exclude={"expected_version"}, exclude_unset=True)


class AddSceneBody(VersionedBody):
    after_index: int = Field(ge=0)
    texto_narrado: str
    prompt_video: str


class MoveSceneBody(VersionedBody):
    target: int = Field(ge=0)


class RegenerateBody(BaseModel):
    model_config = _STRICT
    feedback: str | None = Field(default=None, max_length=500)
    scene_index: int | None = Field(default=None, ge=0)


class ApproveBody(BaseModel):
    model_config = _STRICT
    script_version: int = Field(ge=1)
    max_budget_usd: float | None = Field(default=None, gt=0, le=100)
