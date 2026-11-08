"""Ports de autenticação (provedor de identidade) e do cadastro de membros."""

from typing import Literal, Protocol, runtime_checkable

from videogen.domain.identity import AuthSession, Identity, Member

CodePurpose = Literal["sign-in", "forget-password"]


@runtime_checkable
class IdentityProvider(Protocol):
    """Login. Credencial ou código inválido ⇒ `Unauthorized` (sem dizer qual parte errou)."""

    async def sign_in_password(self, email: str, password: str) -> AuthSession: ...

    async def send_code(self, email: str, purpose: CodePurpose) -> None:
        """Envia um código de uso único por e-mail (entrar ou definir a senha)."""
        ...

    async def sign_in_code(self, email: str, code: str) -> AuthSession: ...

    async def reset_password(self, email: str, code: str, new_password: str) -> None: ...


@runtime_checkable
class SessionVerifier(Protocol):
    async def identify(self, token: str) -> Identity | None:
        """Identidade dona da sessão, ou `None` se expirada/revogada."""
        ...

    async def sign_out(self, token: str) -> None: ...


@runtime_checkable
class MemberDirectory(Protocol):
    async def get(self, email: str) -> Member | None: ...

    async def list_all(self) -> list[Member]: ...

    async def add(self, member: Member) -> Member:
        """`AlreadyExists` se o e-mail já for membro."""
        ...

    async def set_active(self, email: str, active: bool) -> Member:
        """`NotFound` se não for membro."""
        ...
