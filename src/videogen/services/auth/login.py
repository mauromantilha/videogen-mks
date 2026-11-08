"""Login e sessão: o provedor autentica, o app autoriza (só membros ativos entram).

Mensagens de erro não revelam se o e-mail existe; códigos só são enviados a membros ativos.
`resolve` guarda a sessão validada por alguns segundos (chave = hash do token) para não
consultar o provedor a cada requisição — e ainda reflete desativação/papel do membro.
"""

import hashlib
import time
from dataclasses import dataclass, field

from videogen.core.errors import RateLimited, Unauthorized, ValidationFailed
from videogen.domain.identity import (
    AuthSession,
    CurrentUser,
    Identity,
    Member,
    check_password,
    normalize_email,
)
from videogen.ports.identity import CodePurpose, IdentityProvider, MemberDirectory, SessionVerifier

DENIED = "e-mail ou senha inválidos"
CODE_DENIED = "código inválido ou expirado"


@dataclass
class LoginPolicy:
    session_cache_s: float = 60.0
    code_cooldown_s: float = 30.0
    max_cache: int = 1000


@dataclass
class _Cache:
    sessions: dict[str, tuple[float, Identity]] = field(default_factory=dict)
    codes: dict[str, float] = field(default_factory=dict)


class AuthService:
    def __init__(
        self, provider: IdentityProvider, sessions: SessionVerifier, members: MemberDirectory,
        policy: LoginPolicy | None = None,
    ) -> None:  # fmt: skip
        self._provider, self._sessions, self._members = provider, sessions, members
        self._policy = policy or LoginPolicy()
        self._cache = _Cache()

    async def login_password(self, email: str, password: str) -> AuthSession:
        member = await self._active_member(email, DENIED)
        try:
            session = await self._provider.sign_in_password(member.email, password)
        except Unauthorized as exc:
            raise Unauthorized(DENIED) from exc
        return await self._admit(session)

    async def request_code(self, email: str, purpose: CodePurpose) -> None:
        """Envia o código se for membro ativo; para os demais, silêncio (mesma resposta)."""
        try:
            address = normalize_email(email)
        except ValueError as exc:
            raise ValidationFailed("e-mail inválido") from exc
        self._cooldown(f"{purpose}:{address}")
        member = await self._members.get(address)
        if member is not None and member.active:
            await self._provider.send_code(address, purpose)

    async def login_code(self, email: str, code: str) -> AuthSession:
        member = await self._active_member(email, CODE_DENIED)
        try:
            session = await self._provider.sign_in_code(member.email, code.strip())
        except Unauthorized as exc:
            raise Unauthorized(CODE_DENIED) from exc
        return await self._admit(session)

    async def set_password(self, email: str, code: str, new_password: str) -> AuthSession:
        """Primeiro acesso ou senha esquecida: código do e-mail + senha nova ⇒ já entra."""
        try:
            check_password(new_password)
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from exc
        member = await self._active_member(email, CODE_DENIED)
        try:
            await self._provider.reset_password(member.email, code.strip(), new_password)
        except Unauthorized as exc:
            raise Unauthorized(CODE_DENIED) from exc
        return await self.login_password(member.email, new_password)

    async def resolve(self, token: str) -> CurrentUser | None:
        identity = await self._identity(token)
        if identity is None:
            return None
        member = await self._members.get(identity.email)
        if member is None or not member.active:
            return None
        return CurrentUser.of(identity, member)

    async def logout(self, token: str) -> None:
        self._cache.sessions.pop(_key(token), None)
        await self._sessions.sign_out(token)

    async def _identity(self, token: str) -> Identity | None:
        key, now = _key(token), time.monotonic()
        cached = self._cache.sessions.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        identity = await self._sessions.identify(token)
        if identity is None:
            self._cache.sessions.pop(key, None)
            return None
        if len(self._cache.sessions) >= self._policy.max_cache:
            self._cache.sessions.clear()
        self._cache.sessions[key] = (now + self._policy.session_cache_s, identity)
        return identity

    async def _active_member(self, email: str, denied: str) -> Member:
        try:
            member = await self._members.get(normalize_email(email))
        except ValueError:
            member = None
        if member is None or not member.active:
            raise Unauthorized(denied)
        return member

    async def _admit(self, session: AuthSession) -> AuthSession:
        member = await self._members.get(normalize_email(session.identity.email))
        if member is None or not member.active:  # o provedor autenticou outra conta
            await self._sessions.sign_out(session.token)
            raise Unauthorized(DENIED)
        return session

    def _cooldown(self, key: str) -> None:
        now = time.monotonic()
        if self._cache.codes.get(key, 0.0) > now:
            raise RateLimited("aguarde alguns segundos antes de pedir outro código")
        if len(self._cache.codes) >= self._policy.max_cache:
            self._cache.codes = {k: t for k, t in self._cache.codes.items() if t > now}
        self._cache.codes[key] = now + self._policy.code_cooldown_s


def _key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
