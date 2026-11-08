"""Filtros de apresentação da UI."""

from datetime import UTC, datetime

import pytest

from videogen.ui.filters import money, short_dt, status_label, step_label


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "—"),
        (0, "US$ 0,00"),
        (0.003, "US$ 0,003"),
        (0.09, "US$ 0,090"),
        (0.3, "US$ 0,30"),
        (1234.5, "US$ 1.234,50"),
    ],
)
def test_dinheiro_no_formato_brasileiro(value: float | None, text: str) -> None:
    assert money(value) == text


def test_rotulos() -> None:
    assert status_label("awaiting_approval") == "Aguardando aprovação"
    assert step_label("done", cached=True) == "cache" and step_label("running", False) == "rodando"
    assert short_dt(datetime(2026, 11, 8, 13, 5, tzinfo=UTC)) == "08/11 13:05"
