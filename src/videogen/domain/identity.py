"""Identidade e membros: quem entra no app e o que cada um enxerga.

A identidade (senha, código, sessão) vem do provedor de autenticação; a **autorização** é nossa:
só membros ativos entram, e cada job/voz pertence a um usuário (`owner_id`).
"""

import re
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_RE = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")
MAX_EMAIL = 254
MIN_PASSWORD = 10
MAX_PASSWORD = 128


class Role(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > MAX_EMAIL or not EMAIL_RE.match(email):
        raise ValueError("e-mail inválido")
    return email


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[1]


def check_password(password: str) -> None:
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise ValueError(f"a senha deve ter entre {MIN_PASSWORD} e {MAX_PASSWORD} caracteres")


class Member(BaseModel):
    """Pessoa autorizada a usar o app (cadastrada por um admin)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    email: str
    name: str = Field(min_length=1, max_length=120)
    role: Role = Role.MEMBER
    active: bool = True
    created_at: datetime
    created_by: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return normalize_email(value)


class Identity(BaseModel):
    """Usuário autenticado pelo provedor (antes da checagem de membro)."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    email: str
    name: str = ""


class AuthSession(BaseModel):
    """Sessão emitida pelo provedor. O token é opaco e só trafega em cookie HttpOnly."""

    model_config = ConfigDict(frozen=True)

    token: str = Field(min_length=1, repr=False)
    identity: Identity


class CurrentUser(BaseModel):
    """Quem está fazendo a requisição (identidade + papel de membro)."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    email: str
    name: str
    role: Role

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    def can_access(self, owner_id: str | None) -> bool:
        """Cada um vê o que é seu; itens sem dono (anteriores ao login) só os admins veem."""
        if owner_id is None:
            return self.is_admin
        return owner_id == self.user_id

    @classmethod
    def of(cls, identity: Identity, member: Member) -> Self:
        return cls(user_id=identity.user_id, email=member.email,
                   name=member.name or identity.name, role=member.role)  # fmt: skip


LOCAL_USER = CurrentUser(user_id="local", email="local@localhost", name="Local", role=Role.ADMIN)
