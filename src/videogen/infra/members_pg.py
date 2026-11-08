"""Membros no Postgres (Neon), tabela `app.members` — schema em `deploy/sql/001_members.sql`.

O papel do app (`videogen_app`) só tem SELECT/INSERT/UPDATE nessa tabela; o schema é criado
pelo dono do banco, nunca pelo processo da aplicação.
"""

from typing import Any, LiteralString

from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from videogen.core.errors import AlreadyExists, NotFound
from videogen.domain.identity import Member, normalize_email

SELECT_ONE = (
    "SELECT email, name, role, active, created_at, created_by FROM app.members WHERE email = %s"
)
SELECT_ALL = (
    "SELECT email, name, role, active, created_at, created_by FROM app.members ORDER BY email"
)
INSERT = (
    "INSERT INTO app.members (email, name, role, active, created_at, created_by) "
    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING email, name, role, active, created_at, created_by"
)
SET_ACTIVE = (
    "UPDATE app.members SET active = %s WHERE email = %s "
    "RETURNING email, name, role, active, created_at, created_by"
)


class PostgresMemberDirectory:
    def __init__(self, dsn: str, *, max_size: int = 4) -> None:
        self._pool = AsyncConnectionPool(dsn, min_size=0, max_size=max_size, open=False,
                                         kwargs={"autocommit": True})  # fmt: skip

    async def open(self) -> None:
        await self._pool.open(wait=False)

    async def aclose(self) -> None:
        await self._pool.close()

    async def get(self, email: str) -> Member | None:
        rows = await self._fetch(SELECT_ONE, (normalize_email(email),))
        return Member.model_validate(rows[0]) if rows else None

    async def list_all(self) -> list[Member]:
        rows = await self._fetch(SELECT_ALL, ())
        return [Member.model_validate(row) for row in rows]

    async def add(self, member: Member) -> Member:
        values = (member.email, member.name, member.role.value, member.active,
                  member.created_at, member.created_by)  # fmt: skip
        try:
            rows = await self._fetch(INSERT, values)
        except errors.UniqueViolation as exc:
            raise AlreadyExists("já é membro", email=member.email) from exc
        return Member.model_validate(rows[0])

    async def set_active(self, email: str, active: bool) -> Member:
        address = normalize_email(email)
        rows = await self._fetch(SET_ACTIVE, (active, address))
        if not rows:
            raise NotFound("membro não encontrado", email=address)
        return Member.model_validate(rows[0])

    async def _fetch(self, sql: LiteralString, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()
