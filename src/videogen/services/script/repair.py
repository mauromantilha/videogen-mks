"""Parse + validação + reparo da saída do LLM (RF-01): até 1 chamada + N reparos.

Erros baratos de corrigir são perdoados sem gastar outra chamada: cercas de código, numeração
de cenas, `seed` inventada e proporção diferente da pedida.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from videogen.domain.script import AspectRatio, VideoScriptSchema
from videogen.domain.script_rules import RuleViolation, ScriptLimits, validate_rules
from videogen.ports.llm import ChatMessage, LLMProvider
from videogen.services.script.prompts import repair_message

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
DEFAULT_TEMPERATURE = 0.7


@dataclass
class RepairOutcome:
    script: VideoScriptSchema | None
    violations: list[RuleViolation] = field(default_factory=list)
    cost_usd: float = 0.0
    calls: int = 0


class ScriptRepairLoop:
    def __init__(self, max_repairs: int = 2) -> None:
        self._max_repairs = max_repairs

    async def run(
        self,
        llm: LLMProvider,
        messages: Sequence[ChatMessage],
        limits: ScriptLimits,
        aspect_ratio: AspectRatio,
    ) -> RepairOutcome:
        outcome = RepairOutcome(script=None)
        history = list(messages)
        for _ in range(1 + self._max_repairs):
            result = await llm.complete(history, json_mode=True, temperature=DEFAULT_TEMPERATURE)
            outcome.calls += 1
            outcome.cost_usd += result.cost_usd
            script, outcome.violations = parse_and_check(result.text, limits, aspect_ratio)
            if script is not None and not outcome.violations:
                outcome.script = script
                return outcome
            history += [
                ChatMessage(role="assistant", content=result.text),
                repair_message(outcome.violations),
            ]
        return outcome


def parse_and_check(
    text: str, limits: ScriptLimits, aspect_ratio: AspectRatio
) -> tuple[VideoScriptSchema | None, list[RuleViolation]]:
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
    except json.JSONDecodeError as exc:
        return None, [RuleViolation(None, "INVALID_JSON", f"json inválido: {exc.msg}")]
    try:
        script = VideoScriptSchema.model_validate(_forgive(data, aspect_ratio))
    except ValidationError as exc:
        return None, [_schema_violation(error) for error in exc.errors()]
    return script, validate_rules(script, limits)


def _forgive(data: Any, aspect_ratio: AspectRatio) -> Any:
    if not isinstance(data, dict) or not isinstance(data.get("cenas"), list):
        return data
    scenes = [
        {k: v for k, v in scene.items() if k != "seed"} | {"scene_index": i}
        if isinstance(scene, dict)
        else scene
        for i, scene in enumerate(data["cenas"])
    ]
    return data | {"cenas": scenes, "aspect_ratio": aspect_ratio}


def _schema_violation(error: Any) -> RuleViolation:
    location = tuple(error.get("loc", ()))
    index = location[1] if len(location) > 1 and location[0] == "cenas" else None
    where = ".".join(str(part) for part in location) or "roteiro"
    message = f"{where}: {error.get('msg', 'inválido')}"
    return RuleViolation(index if isinstance(index, int) else None, "SCHEMA", message)
