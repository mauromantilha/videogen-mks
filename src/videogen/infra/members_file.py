"""Membros num JSON do workspace (`_members.json`): desenvolvimento e testes, sem Postgres."""

import asyncio
import json
from pathlib import Path

from videogen.core.errors import AlreadyExists, NotFound
from videogen.domain.identity import Member, normalize_email
from videogen.infra.atomic_file import write_atomic


class FileMemberDirectory:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def get(self, email: str) -> Member | None:
        return (await self._load()).get(normalize_email(email))

    async def list_all(self) -> list[Member]:
        return sorted((await self._load()).values(), key=lambda member: member.email)

    async def add(self, member: Member) -> Member:
        async with self._lock:
            members = await self._load()
            if member.email in members:
                raise AlreadyExists("já é membro", email=member.email)
            members[member.email] = member
            await self._save(members)
        return member

    async def set_active(self, email: str, active: bool) -> Member:
        address = normalize_email(email)
        async with self._lock:
            members = await self._load()
            if address not in members:
                raise NotFound("membro não encontrado", email=address)
            members[address] = members[address].model_copy(update={"active": active})
            await self._save(members)
        return members[address]

    async def _load(self) -> dict[str, Member]:
        if not self._path.is_file():
            return {}
        raw = await asyncio.to_thread(self._path.read_bytes)
        return {item["email"]: Member.model_validate(item) for item in json.loads(raw)}

    async def _save(self, members: dict[str, Member]) -> None:
        payload = json.dumps([m.model_dump(mode="json") for m in members.values()], indent=2)
        await asyncio.to_thread(write_atomic, self._path, payload.encode("utf-8"))
