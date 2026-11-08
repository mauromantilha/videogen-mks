"""Montagem da autenticação: provedor (Neon Auth ou nenhum) e cadastro de membros.

- `AUTH_MODE=local`: sem login (só loopback); membros num JSON do workspace (tela de usuários).
- `AUTH_MODE=neon`: Neon Auth pelo servidor; membros no Postgres se `DATABASE_URL` existir.
"""

import logging
from dataclasses import dataclass

import httpx

from videogen.core.clock import Clock
from videogen.core.config import Settings
from videogen.infra.members_file import FileMemberDirectory
from videogen.infra.members_pg import PostgresMemberDirectory
from videogen.infra.workspace import Workspace
from videogen.ports.identity import MemberDirectory
from videogen.providers.neon_auth.identity import NeonAuthIdentity
from videogen.services.auth.login import AuthService, LoginPolicy
from videogen.services.auth.members import MemberService

logger = logging.getLogger(__name__)
MEMBERS_FILE = "_members.json"


@dataclass(frozen=True)
class AuthParts:
    login: AuthService | None
    members: MemberService
    directory: MemberDirectory
    client: httpx.AsyncClient | None
    bootstrap_admin: str | None

    async def startup(self) -> None:
        if isinstance(self.directory, PostgresMemberDirectory):
            await self.directory.open()
        try:
            created = await self.members.bootstrap(self.bootstrap_admin)
        except Exception:  # banco fora do ar não impede o app de subir (o /login acusa)
            logger.exception("falha ao garantir o admin inicial")
            return
        if created is not None:
            logger.info("admin inicial garantido", extra={"email": created.email})

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()
        if isinstance(self.directory, PostgresMemberDirectory):
            await self.directory.aclose()


def build_auth(settings: Settings, workspace: Workspace, clock: Clock) -> AuthParts:
    auth = settings.auth
    directory = _directory(settings, workspace)
    members = MemberService(directory, clock, auth.auth_allowed_domain)
    if auth.auth_mode != "neon" or not auth.neon_auth_url:
        return AuthParts(None, members, directory, None, auth.auth_bootstrap_admin)
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False)
    identity = NeonAuthIdentity(auth.neon_auth_url, auth.app_public_url, client)
    login = AuthService(identity, identity, directory, LoginPolicy(auth.session_cache_s))
    return AuthParts(login, members, directory, client, auth.auth_bootstrap_admin)


def _directory(settings: Settings, workspace: Workspace) -> MemberDirectory:
    url = settings.auth.database_url
    if url is not None and url.get_secret_value():
        return PostgresMemberDirectory(url.get_secret_value())
    return FileMemberDirectory(workspace.root / MEMBERS_FILE)
