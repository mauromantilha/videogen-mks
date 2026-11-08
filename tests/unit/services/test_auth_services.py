"""Login por usuário: o provedor autentica, o app autoriza (membros) — e cada um vê o que é seu."""

from pathlib import Path

import pytest

from tests.fakes.fake_clock import FakeClock
from tests.fakes.identity import FakeIdentityProvider
from videogen.core.errors import (
    AlreadyExists,
    Forbidden,
    NotFound,
    RateLimited,
    Unauthorized,
    ValidationFailed,
)
from videogen.domain.identity import CurrentUser, Member, Role
from videogen.infra.members_file import FileMemberDirectory
from videogen.services.auth.login import AuthService, LoginPolicy
from videogen.services.auth.members import MemberService

ANA = "ana@mksseguros.com"
ADMIN = CurrentUser(user_id="u-admin", email="chefe@mksseguros.com", name="Chefe", role=Role.ADMIN)


@pytest.fixture
def directory(tmp_path: Path) -> FileMemberDirectory:
    return FileMemberDirectory(tmp_path / "members.json")


@pytest.fixture
def idp() -> FakeIdentityProvider:
    return FakeIdentityProvider()


@pytest.fixture
def auth(idp: FakeIdentityProvider, directory: FileMemberDirectory) -> AuthService:
    return AuthService(idp, idp, directory, LoginPolicy(code_cooldown_s=0))


async def _member(directory: FileMemberDirectory, email: str = ANA, **extra: object) -> Member:
    return await directory.add(Member(email=email, name="Ana", created_at=FakeClock().now(),
                                      **extra))  # type: ignore[arg-type]  # fmt: skip


async def test_senha_so_vale_para_membro_ativo(
    auth: AuthService, idp: FakeIdentityProvider, directory: FileMemberDirectory
) -> None:
    idp.add_user(ANA, "senha-forte-1")
    with pytest.raises(Unauthorized, match="e-mail ou senha"):  # existe no provedor, não é membro
        await auth.login_password(ANA, "senha-forte-1")
    await _member(directory)
    session = await auth.login_password("  ANA@mksseguros.com ", "senha-forte-1")
    user = await auth.resolve(session.token)
    assert user is not None and (user.email, user.role) == (ANA, Role.MEMBER)
    with pytest.raises(Unauthorized):
        await auth.login_password(ANA, "errada")


async def test_codigo_por_email_so_e_enviado_a_membros(
    auth: AuthService, idp: FakeIdentityProvider, directory: FileMemberDirectory
) -> None:
    await auth.request_code("estranho@mksseguros.com", "sign-in")
    assert idp.sent == []  # mesma resposta, nenhum e-mail
    await _member(directory)
    await auth.request_code(ANA, "sign-in")
    session = await auth.login_code(ANA, idp.last_code(ANA))
    assert (await auth.resolve(session.token)) is not None
    with pytest.raises(Unauthorized, match="código"):  # código de uso único
        await auth.login_code(ANA, "000000")


async def test_primeiro_acesso_define_senha_e_entra(
    auth: AuthService, idp: FakeIdentityProvider, directory: FileMemberDirectory
) -> None:
    idp.add_user(ANA)  # criada sem senha (como no Neon)
    await _member(directory)
    await auth.request_code(ANA, "forget-password")
    with pytest.raises(ValidationFailed, match="10"):
        await auth.set_password(ANA, idp.last_code(ANA, "forget-password"), "curta")
    session = await auth.set_password(ANA, idp.last_code(ANA, "forget-password"), "nova-senha-123")
    assert (await auth.resolve(session.token)) is not None
    assert (await auth.login_password(ANA, "nova-senha-123")).identity.email == ANA


async def test_membro_desativado_perde_o_acesso_na_hora(
    auth: AuthService, idp: FakeIdentityProvider, directory: FileMemberDirectory
) -> None:
    idp.add_user(ANA, "senha-forte-1")
    await _member(directory)
    session = await auth.login_password(ANA, "senha-forte-1")
    await directory.set_active(ANA, False)
    assert await auth.resolve(session.token) is None  # o cache guarda só a identidade
    await directory.set_active(ANA, True)
    await auth.logout(session.token)
    assert await auth.resolve(session.token) is None


async def test_pedidos_de_codigo_tem_intervalo_minimo(
    idp: FakeIdentityProvider, directory: FileMemberDirectory
) -> None:
    auth = AuthService(idp, idp, directory, LoginPolicy(code_cooldown_s=30))
    await _member(directory)
    await auth.request_code(ANA, "sign-in")
    with pytest.raises(RateLimited):
        await auth.request_code(ANA, "sign-in")
    await auth.request_code(ANA, "forget-password")  # finalidade diferente: liberado


async def test_cadastro_de_membros_exige_admin_e_dominio(directory: FileMemberDirectory) -> None:
    service = MemberService(directory, FakeClock(), "mksseguros.com")
    member = await service.add(ADMIN, " Ana@MKSseguros.com ", "  Ana   Lima ", Role.MEMBER)
    assert (member.email, member.name, member.created_by) == (ANA, "Ana Lima", ADMIN.email)
    with pytest.raises(AlreadyExists):
        await service.add(ADMIN, ANA, "Ana", Role.MEMBER)
    with pytest.raises(ValidationFailed, match=r"@mksseguros\.com"):
        await service.add(ADMIN, "alguem@gmail.com", "X", Role.MEMBER)
    comum = CurrentUser(user_id="u-ana", email=ANA, name="Ana", role=Role.MEMBER)
    with pytest.raises(Forbidden):
        await service.add(comum, "bia@mksseguros.com", "Bia", Role.ADMIN)
    with pytest.raises(Forbidden):
        await service.list_all(comum)
    with pytest.raises(ValidationFailed, match="própria"):
        await service.set_active(ADMIN, ADMIN.email, False)
    with pytest.raises(NotFound):
        await service.set_active(ADMIN, "ninguem@mksseguros.com", False)
    assert not (await service.set_active(ADMIN, ANA, False)).active


async def test_admin_inicial_so_e_criado_se_nao_houver_nenhum(
    directory: FileMemberDirectory,
) -> None:
    service = MemberService(directory, FakeClock(), "mksseguros.com")
    assert await service.bootstrap(None) is None
    created = await service.bootstrap("Comercial@mksseguros.com")
    assert created is not None and (created.email, created.role) == (
        "comercial@mksseguros.com", Role.ADMIN)  # fmt: skip
    assert await service.bootstrap("outro@mksseguros.com") is None  # já há admin
    assert len(await directory.list_all()) == 1


def test_cada_um_ve_o_que_e_seu() -> None:
    ana = CurrentUser(user_id="u-ana", email=ANA, name="Ana", role=Role.MEMBER)
    assert ana.can_access("u-ana") and not ana.can_access("u-bia")
    assert not ana.can_access(None)  # itens anteriores ao login: só admins
    assert ADMIN.can_access(None) and not ADMIN.can_access("u-ana")
