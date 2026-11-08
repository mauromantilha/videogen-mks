"""Filtros Jinja da UI (apresentação em pt-BR; nenhuma regra de negócio)."""

from datetime import datetime

from videogen.domain.script_rules import count_words

STATUS_LABELS = {
    "scripting": "Gerando roteiro", "awaiting_approval": "Aguardando aprovação",
    "approved": "Aprovado", "rendering": "Renderizando", "finalizing": "Finalizando",
    "completed": "Concluído", "failed": "Falhou", "canceled": "Cancelado",
}  # fmt: skip
STEP_LABELS = {"pending": "pendente", "running": "rodando", "done": "ok", "failed": "erro"}


SMALL_AMOUNT = 0.1


def money(value: float | None) -> str:
    """US$ no formato brasileiro; valores pequenos (ex.: LLM) ganham a 3ª casa."""
    if value is None:
        return "—"
    digits = 3 if 0 < value < SMALL_AMOUNT else 2
    return f"US$ {value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def short_dt(value: datetime) -> str:
    return value.strftime("%d/%m %H:%M")


def status_label(value: str) -> str:
    return STATUS_LABELS.get(str(value), str(value))


def step_label(status: str, cached: bool) -> str:
    return "cache" if cached and status == "done" else STEP_LABELS.get(str(status), str(status))


FILTERS = {"money": money, "short_dt": short_dt, "status_label": status_label,
           "step_label": step_label, "words": count_words}  # fmt: skip
