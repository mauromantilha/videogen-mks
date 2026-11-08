"""LLM simulado: roteiro determinístico e válido, ou respostas roteirizadas (testes)."""

import json
import re
from collections.abc import Sequence

from videogen.ports.llm import ChatMessage, LLMResult, LLMUsage

DEFAULT_SCENES = 3
_SCENES = re.compile(r"(\d+)\s+cenas", re.IGNORECASE)
_THEME = re.compile(r"^Tema:\s*(.+)$", re.MULTILINE)
_NARRATIONS = (
    "Imagine proteger o seu futuro com um clique.",
    "Planos simples que cabem no seu bolso.",
    "Sua família segura em qualquer momento.",
    "Contrate agora e durma tranquilo hoje.",
)
_SHOTS = (
    "A young woman smiles at her phone in a sunlit apartment, warm light, slow dolly-in",
    "Hands holding a coffee cup near a window, soft morning light, shallow depth of field",
    "A family walking in a park at golden hour, tracking shot, cinematic",
    "A calm bedroom at night with city lights outside, slow pan, moody lighting",
)


class FakeLLM:
    def __init__(self, responses: Sequence[str] = ()) -> None:
        self._responses = list(responses)  # se houver, são devolvidas em ordem
        self.calls: list[list[ChatMessage]] = []

    async def complete(
        self, messages: Sequence[ChatMessage], *, json_mode: bool, temperature: float | None
    ) -> LLMResult:
        self.calls.append(list(messages))
        text = self._responses.pop(0) if self._responses else self._script(messages)
        return LLMResult(text=text, usage=LLMUsage(prompt_tokens=100, completion_tokens=200))

    @staticmethod
    def _script(messages: Sequence[ChatMessage]) -> str:
        prompt = "\n".join(message.content for message in messages)
        scenes = int(match.group(1)) if (match := _SCENES.search(prompt)) else DEFAULT_SCENES
        theme = match.group(1).strip()[:200] if (match := _THEME.search(prompt)) else "Tema fake"
        script = {
            "produto_tema": theme,
            "aspect_ratio": "9:16",
            "estilo_visual": "cinematic, warm light, consistent color grading",
            "cenas": [
                {
                    "scene_index": i,
                    "texto_narrado": _NARRATIONS[i % len(_NARRATIONS)],
                    "prompt_video": _SHOTS[i % len(_SHOTS)],
                }
                for i in range(scenes)
            ],
        }
        return json.dumps(script, ensure_ascii=False)
