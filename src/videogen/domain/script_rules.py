"""Regras de negócio do roteiro além do schema (RF-01, RF-07).

Devolve uma lista de violações por cena: a UI mostra no cartão da cena e o repair loop
devolve ao LLM. Heurísticas são deliberadamente simples e baratas; o usuário pode editar.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from videogen.core.errors import ValidationFailed
from videogen.domain.script import SceneSpec, VideoScriptSchema

_WORD_CHAR = re.compile(r"\w")
_SPEECH = re.compile(
    r"\b(talk|speak|say|explain|address)\w*\s+(directly\s+)?(to|into|at|toward)\s+(the\s+)?"
    r"(camera|viewer|audience)\b|\blip[- ]?sync\w*|\bmouths?\s+moving\b",
    re.IGNORECASE,
)
_ON_SCREEN_TEXT = re.compile(
    r"\b(on[- ]screen text|text overlay|captions?|subtitles?|watermarks?|logos?|typography"
    r"|lettering|written text)\b|\b(sign|banner|poster|screen)\s+(that\s+)?(says|reads)\b",
    re.IGNORECASE,
)
_PT_STOPWORDS = frozenset(
    "de que não uma com para os das dos em um é pela pelo na seu sua mais como".split()
)
_EN_STOPWORDS = frozenset("the of with in on and at to is an her his their from by".split())
_MIN_PT_HITS = 2


@dataclass(frozen=True)
class ScriptLimits:
    scene_seconds: float = 4.0
    words_per_second: float = 3.0
    expected_scenes: int | None = None  # só na saída do LLM; edição manual pode mudar N

    @property
    def max_words(self) -> int:
        return int(self.scene_seconds * self.words_per_second)


@dataclass(frozen=True)
class RuleViolation:
    scene_index: int | None  # None = violação do roteiro inteiro
    code: str
    message: str


class ScriptValidationError(ValidationFailed):
    code = "SCRIPT_INVALID"

    def __init__(self, violations: Sequence[RuleViolation]) -> None:
        self.violations = tuple(violations)
        super().__init__(f"roteiro inválido: {len(self.violations)} violação(ões)")


def count_words(text: str) -> int:
    """Palavras faladas: tokens com ao menos uma letra/dígito (pontuação solta não conta)."""
    return sum(1 for token in text.split() if _WORD_CHAR.search(token))


def looks_portuguese(text: str) -> bool:
    tokens = re.findall(r"[a-zà-ú]+", text.lower())
    pt_hits = sum(token in _PT_STOPWORDS for token in tokens)
    en_hits = sum(token in _EN_STOPWORDS for token in tokens)
    return pt_hits >= _MIN_PT_HITS and pt_hits > en_hits


def _scene_violations(scene: SceneSpec, limits: ScriptLimits) -> Iterator[RuleViolation]:
    index = scene.scene_index
    words = count_words(scene.texto_narrado)
    if words == 0:
        yield RuleViolation(index, "EMPTY_NARRATION", "a narração não tem palavras")
    elif words > limits.max_words:
        message = f"{words} palavras; máximo {limits.max_words} para {limits.scene_seconds:g}s"
        yield RuleViolation(index, "TOO_MANY_WORDS", message)
    if looks_portuguese(scene.prompt_video):
        yield RuleViolation(index, "PROMPT_NOT_ENGLISH", "prompt_video deve estar em inglês")
    if _SPEECH.search(scene.prompt_video):
        message = "o vídeo não tem lip-sync: evite pessoas falando para a câmera"
        yield RuleViolation(index, "PROMPT_HAS_SPEECH", message)
    if _ON_SCREEN_TEXT.search(scene.prompt_video):
        message = "não peça texto, legenda ou logo na imagem; a legenda é aplicada depois"
        yield RuleViolation(index, "PROMPT_HAS_TEXT", message)


def validate_rules(script: VideoScriptSchema, limits: ScriptLimits) -> list[RuleViolation]:
    found: list[RuleViolation] = []
    expected = limits.expected_scenes
    if expected is not None and len(script.cenas) != expected:
        message = f"{len(script.cenas)} cenas; esperado {expected}"
        found.append(RuleViolation(None, "SCENE_COUNT", message))
    for scene in script.cenas:
        found.extend(_scene_violations(scene, limits))
    return found


def ensure_valid(script: VideoScriptSchema, limits: ScriptLimits) -> None:
    """Levanta `ScriptValidationError` com todas as violações, ou não faz nada."""
    if violations := validate_rules(script, limits):
        raise ScriptValidationError(violations)
