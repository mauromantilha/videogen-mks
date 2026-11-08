"""Provedor de identidade em memória, com a semântica observada no Neon Auth:

- código de entrada cria o usuário se ainda não existir (sign-up por OTP);
- redefinir senha exige usuário existente e código `forget-password` válido;
- código errado/expirado ⇒ `Unauthorized`; cada código vale uma vez.
"""

import secrets
from dataclasses import dataclass, field

from videogen.core.errors import Unauthorized
from videogen.domain.identity import AuthSession, Identity
from videogen.ports.identity import CodePurpose


@dataclass
class FakeIdentityProvider:
    passwords: dict[str, str] = field(default_factory=dict)
    users: dict[str, Identity] = field(default_factory=dict)
    codes: dict[tuple[str, CodePurpose], str] = field(default_factory=dict)
    sessions: dict[str, Identity] = field(default_factory=dict)
    sent: list[tuple[str, CodePurpose]] = field(default_factory=list)

    def add_user(self, email: str, password: str | None = None) -> Identity:
        identity = Identity(user_id=f"user-{len(self.users) + 1}", email=email,
                            name=email.split("@")[0])  # fmt: skip
        self.users[email] = identity
        if password is not None:
            self.passwords[email] = password
        return identity

    def last_code(self, email: str, purpose: CodePurpose = "sign-in") -> str:
        return self.codes[(email, purpose)]

    async def sign_in_password(self, email: str, password: str) -> AuthSession:
        if email not in self.passwords or self.passwords[email] != password:
            raise Unauthorized("e-mail ou senha inválidos")
        return self._session(self.users[email])

    async def send_code(self, email: str, purpose: CodePurpose) -> None:
        self.sent.append((email, purpose))
        if purpose == "forget-password" and email not in self.users:
            return  # o Neon responde sucesso e não envia nada
        self.codes[(email, purpose)] = f"{secrets.randbelow(10**6):06d}"

    async def sign_in_code(self, email: str, code: str) -> AuthSession:
        self._consume(email, "sign-in", code)
        identity = self.users.get(email) or self.add_user(email)
        return self._session(identity)

    async def reset_password(self, email: str, code: str, new_password: str) -> None:
        self._consume(email, "forget-password", code)
        self.passwords[email] = new_password
        for token in [t for t, who in self.sessions.items() if who.email == email]:
            del self.sessions[token]  # revoke_sessions_on_password_reset

    async def identify(self, token: str) -> Identity | None:
        return self.sessions.get(token)

    async def sign_out(self, token: str) -> None:
        self.sessions.pop(token, None)

    def _consume(self, email: str, purpose: CodePurpose, code: str) -> None:
        if self.codes.pop((email, purpose), None) != code:
            raise Unauthorized("código inválido ou expirado")

    def _session(self, identity: Identity) -> AuthSession:
        token = secrets.token_urlsafe(24)
        self.sessions[token] = identity
        return AuthSession(token=token, identity=identity)
