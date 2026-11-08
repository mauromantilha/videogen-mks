"""Quebra a narração em linhas curtas e distribui o tempo da fala entre elas.

Sem alinhamento forçado na v1: cada linha dura proporcionalmente ao seu nº de caracteres e
a última termina exatamente no fim do áudio.
"""

from dataclasses import dataclass

_BREAK_AFTER = (".", ",", "!", "?", ";", ":", "—")
_MIN_WORDS_BEFORE_BREAK = 2


@dataclass(frozen=True)
class TimedLine:
    start_s: float
    end_s: float
    text: str


def chunk_phrases(text: str, *, max_words: int, max_chars: int) -> list[str]:
    """Agrupa palavras em linhas, preferindo quebrar após pontuação."""
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        candidate = " ".join([*current, word])
        if current and (len(current) >= max_words or len(candidate) > max_chars):
            lines.append(" ".join(current))
            current = []
        current.append(word)
        if word.endswith(_BREAK_AFTER) and len(current) >= _MIN_WORDS_BEFORE_BREAK:
            lines.append(" ".join(current))
            current = []
    if current:
        lines.append(" ".join(current))
    return lines


def timed_lines(text: str, duration_s: float, *, max_words: int, max_chars: int) -> list[TimedLine]:
    phrases = chunk_phrases(text, max_words=max_words, max_chars=max_chars)
    if not phrases or duration_s <= 0:
        return []
    weights = [max(1, len(phrase)) for phrase in phrases]
    total = sum(weights)
    timed: list[TimedLine] = []
    start = 0.0
    for index, (phrase, weight) in enumerate(zip(phrases, weights, strict=True)):
        end = duration_s if index == len(phrases) - 1 else start + duration_s * weight / total
        timed.append(TimedLine(start_s=start, end_s=end, text=phrase))
        start = end
    return timed
