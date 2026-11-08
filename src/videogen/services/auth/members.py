"""Cadastro de membros da organização (só admins), restrito ao domínio de e-mail da empresa.

A pessoa cadastrada entra pela primeira vez com um código enviado ao e-mail e, se quiser,
define a senha depois ("Definir senha"). Ninguém escolhe senha por ela.
"""

from videogen.core.clock import Clock
from videogen.core.errors import Forbidden, ValidationFailed
from videogen.domain.identity import CurrentUser, Member, Role, email_domain, normalize_email
from videogen.ports.identity import MemberDirectory


class MemberService:
    def __init__(self, directory: MemberDirectory, clock: Clock, allowed_domain: str) -> None:
        self._directory = directory
        self._clock = clock
        self._domain = allowed_domain.strip().lower()

    async def list_all(self, actor: CurrentUser) -> list[Member]:
        _require_admin(actor)
        return await self._directory.list_all()

    async def add(self, actor: CurrentUser, email: str, name: str, role: Role) -> Member:
        _require_admin(actor)
        address = self._checked_email(email)
        if not name.strip():
            raise ValidationFailed("informe o nome")
        member = Member(email=address, name=" ".join(name.split()), role=role,
                        created_at=self._clock.now(), created_by=actor.email)  # fmt: skip
        return await self._directory.add(member)

    async def set_active(self, actor: CurrentUser, email: str, active: bool) -> Member:
        _require_admin(actor)
        address = self._checked_email(email)
        if address == actor.email and not active:
            raise ValidationFailed("você não pode desativar a própria conta")
        return await self._directory.set_active(address, active)

    async def bootstrap(self, email: str | None) -> Member | None:
        """Startup: garante um admin inicial (só age se ainda não houver nenhum admin ativo)."""
        if not email:
            return None
        members = await self._directory.list_all()
        if any(m.role is Role.ADMIN and m.active for m in members):
            return None
        address = normalize_email(email)
        existing = next((m for m in members if m.email == address), None)
        if existing is not None:
            return existing
        admin = Member(email=address, name=address.split("@")[0], role=Role.ADMIN,
                       created_at=self._clock.now(), created_by="bootstrap")  # fmt: skip
        return await self._directory.add(admin)

    def _checked_email(self, email: str) -> str:
        try:
            address = normalize_email(email)
        except ValueError as exc:
            raise ValidationFailed("e-mail inválido") from exc
        if self._domain and email_domain(address) != self._domain:
            raise ValidationFailed(f"só e-mails @{self._domain} podem ser cadastrados")
        return address


def _require_admin(actor: CurrentUser) -> None:
    if not actor.is_admin:
        raise Forbidden("apenas administradores gerenciam usuários")
