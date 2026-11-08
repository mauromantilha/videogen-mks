"""Membros no Postgres: conexão derrubada pela hibernação do Neon não vira erro 500."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from psycopg import errors

from videogen.core.errors import ProviderError
from videogen.infra.members_pg import PostgresMemberDirectory

ROW = {"email": "ana@mksseguros.com", "name": "Ana", "role": "member", "active": True,
       "created_at": datetime(2026, 11, 8, tzinfo=UTC), "created_by": None}  # fmt: skip


class FlakyPool:
    """Imita o `AsyncConnectionPool`: as primeiras `failures` consultas caem como no Neon."""

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    @asynccontextmanager
    async def connection(self) -> AsyncIterator["FlakyPool"]:
        yield self

    @asynccontextmanager
    async def cursor(self, row_factory: Any = None) -> AsyncIterator["FlakyPool"]:
        yield self

    async def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise errors.AdminShutdown("terminating connection due to administrator command")

    async def fetchall(self) -> list[dict[str, Any]]:
        return [ROW]


def _directory(pool: FlakyPool) -> PostgresMemberDirectory:
    directory = PostgresMemberDirectory("postgresql://ninguem@localhost/x")
    directory._pool = pool
    return directory


async def test_conexao_derrubada_e_refeita_uma_vez() -> None:
    pool = FlakyPool(failures=1)
    member = await _directory(pool).get("ANA@mksseguros.com")
    assert member is not None and member.email == ROW["email"]
    assert pool.calls == 2


async def test_banco_fora_do_ar_vira_erro_de_dominio() -> None:
    pool = FlakyPool(failures=2)
    with pytest.raises(ProviderError, match="indisponível"):
        await _directory(pool).list_all()
    assert pool.calls == 2
