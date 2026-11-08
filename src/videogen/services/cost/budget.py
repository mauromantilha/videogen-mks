"""Orçamento por job (RNF-10)."""

from videogen.core.errors import BudgetExceeded

_EPSILON = 1e-9


def ensure_within(estimated_usd: float, budget_usd: float) -> None:
    """Aprovação: o que ainda será gasto precisa caber no orçamento."""
    if estimated_usd > budget_usd + _EPSILON:
        raise BudgetExceeded(
            f"custo estimado US$ {estimated_usd:.3f} excede o orçamento US$ {budget_usd:.2f}",
            estimated_usd=round(estimated_usd, 6),
            budget_usd=budget_usd,
        )


def allows_new_attempt(spent_usd: float, budget_usd: float) -> bool:
    """Render: depois de estourar, nenhuma tentativa nova começa (as em voo terminam)."""
    return spent_usd < budget_usd - _EPSILON
