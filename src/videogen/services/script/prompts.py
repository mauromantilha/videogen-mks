"""Mensagens do LLM roteirista (funções puras).

O tema do usuário vai isolado na mensagem `user` e com quebras de linha removidas, para não
conseguir injetar instruções (ex.: "Gere 10 cenas"). As regras ficam no `system`; o validador
determinístico confere tudo de novo — o prompt orienta, não garante.
"""

import json

from videogen.domain.request import JobRequest
from videogen.domain.script import VideoScriptSchema
from videogen.domain.script_rules import RuleViolation, ScriptLimits
from videogen.ports.llm import ChatMessage

_FRAMING = {
    "9:16": "vertical (9:16): sujeito centralizado, planos médios e fechados",
    "16:9": "horizontal (16:9): composições amplas e planos abertos",
}
_EXAMPLE = {
    "produto_tema": "Seguro de vida",
    "aspect_ratio": "9:16",
    "estilo_visual": "cinematic, warm natural light, shallow depth of field, same young woman",
    "cenas": [
        {
            "scene_index": 0,
            "texto_narrado": "Imagine proteger o seu futuro com um clique.",
            "prompt_video": "A young woman smiles at her phone in a sunlit apartment, "
            "warm morning light, slow dolly-in, cinematic",
        }
    ],
}


def system_prompt(limits: ScriptLimits, aspect_ratio: str) -> str:
    return f"""Você é roteirista de vídeos curtos para redes sociais.
Responda SOMENTE com um objeto json válido, sem texto antes ou depois, neste formato:
{json.dumps(_EXAMPLE, ensure_ascii=False)}

Regras:
- Arco narrativo: gancho na primeira cena, desenvolvimento, chamada para ação na última.
- "texto_narrado": português do Brasil, no máximo {limits.max_words} palavras por cena
  ({limits.scene_seconds:g} segundos de fala), sem emojis, sem hashtags.
- "prompt_video": em INGLÊS, descrevendo sujeito, ação, cenário, iluminação e movimento de câmera.
- Enquadramento {_FRAMING.get(aspect_ratio, aspect_ratio)}.
- Proibido no vídeo: texto, legendas, letreiros, logotipos, marcas registradas e pessoas
  falando para a câmera (o vídeo não tem sincronia labial).
- Mantenha personagens, figurino e paleta consistentes entre as cenas e resuma o estilo
  comum em "estilo_visual" (inglês).
- "scene_index" começa em 0 e é sequencial. Não inclua o campo "seed"."""


def _user(request: JobRequest, count: int) -> str:
    theme = " ".join(request.tema.split())
    return f"Tema: {theme}\nGere exatamente {count} cenas."


def draft_messages(request: JobRequest, limits: ScriptLimits) -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content=system_prompt(limits, request.aspect_ratio)),
        ChatMessage(role="user", content=_user(request, request.n_cenas)),
    ]


def regenerate_messages(
    request: JobRequest,
    current: VideoScriptSchema,
    limits: ScriptLimits,
    *,
    feedback: str | None,
    scene_index: int | None,
) -> list[ChatMessage]:
    """Pede o roteiro completo de volta; para uma cena, só ela pode mudar (o serviço enxerta)."""
    target = (
        "Reescreva TODAS as cenas."
        if scene_index is None
        else f"Reescreva SOMENTE a cena {scene_index}; repita as demais sem alterações."
    )
    note = f"\nAjuste pedido pelo usuário: {' '.join(feedback.split())}" if feedback else ""
    content = (
        f"{_user(request, len(current.cenas))}\nRoteiro atual:\n"
        f"{current.model_dump_json(exclude={'cenas': {'__all__': {'seed'}}})}\n"
        f"{target}{note}"
    )
    return [
        ChatMessage(role="system", content=system_prompt(limits, request.aspect_ratio)),
        ChatMessage(role="user", content=content),
    ]


def repair_message(violations: list[RuleViolation]) -> ChatMessage:
    lines = [
        f"- {'roteiro' if v.scene_index is None else f'cena {v.scene_index}'}: {v.message}"
        for v in violations
    ]
    return ChatMessage(
        role="user",
        content="O json anterior tem problemas. Corrija e responda "
        "apenas com o json completo:\n" + "\n".join(lines),
    )
