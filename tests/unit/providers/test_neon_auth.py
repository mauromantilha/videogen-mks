"""Adapter do Neon Auth contra respostas gravadas do serviço real (formato de 2026-11-08)."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from videogen.core.errors import ProviderError, RateLimited, Unauthorized
from videogen.providers.neon_auth.identity import SESSION_COOKIE, NeonAuthIdentity

BASE = "https://ep-x.neonauth.example.aws.neon.tech/videogen/auth"
ORIGIN = "https://video.mksseguros.com"
USER = {"id": "2f0b92c2-5666-473b-b0ef-a0c238fb21c0", "email": "Comercial@mksseguros.com",
        "name": "Comercial MKS", "emailVerified": False}  # fmt: skip
COOKIE = f"{SESSION_COOKIE}=tok.assinado; Max-Age=604800; Path=/; HttpOnly; Secure; SameSite=None"


@pytest.fixture
async def neon() -> AsyncIterator[NeonAuthIdentity]:
    async with httpx.AsyncClient() as client:
        yield NeonAuthIdentity(BASE + "/", ORIGIN, client)


@respx.mock
async def test_login_com_senha_extrai_o_token_do_cookie(neon: NeonAuthIdentity) -> None:
    route = respx.post(f"{BASE}/sign-in/email").respond(
        200, json={"redirect": False, "token": "x", "user": USER},
        headers=[("set-cookie", "outro=1; Path=/"), ("set-cookie", COOKIE)],
    )  # fmt: skip
    session = await neon.sign_in_password("comercial@mksseguros.com", "segredo-123")
    assert session.token == "tok.assinado"
    assert (session.identity.user_id, session.identity.email) == (USER["id"], USER["email"].lower())
    sent = route.calls.last.request
    assert sent.headers["origin"] == ORIGIN
    body = {"email": "comercial@mksseguros.com", "password": "segredo-123"}
    assert json.loads(sent.content) == body
    assert "segredo-123" not in repr(session)


@respx.mock
async def test_erros_viram_erros_de_dominio(neon: NeonAuthIdentity) -> None:
    respx.post(f"{BASE}/sign-in/email").respond(
        401, json={"message": "Invalid email or password", "code": "INVALID_EMAIL_OR_PASSWORD"}
    )
    with pytest.raises(Unauthorized):
        await neon.sign_in_password("a@b.com", "x")
    respx.post(f"{BASE}/sign-in/email-otp").respond(400, json={"code": "INVALID_OTP"})
    with pytest.raises(Unauthorized):
        await neon.sign_in_code("a@b.com", "000000")
    respx.post(f"{BASE}/email-otp/reset-password").respond(429, json={"message": "slow down"})
    with pytest.raises(RateLimited):
        await neon.reset_password("a@b.com", "1", "nova-senha-123")
    origin_error = {"code": "INVALID_ORIGIN"}
    respx.post(f"{BASE}/email-otp/send-verification-otp").respond(403, json=origin_error)
    with pytest.raises(ProviderError) as info:  # configuração errada não vira "senha errada"
        await neon.send_code("a@b.com", "sign-in")
    assert info.value.context["provider_code"] == "INVALID_ORIGIN"


@respx.mock
async def test_login_sem_cookie_de_sessao_e_recusado(neon: NeonAuthIdentity) -> None:
    respx.post(f"{BASE}/sign-in/email-otp").respond(200, json={"user": USER})
    with pytest.raises(Unauthorized):
        await neon.sign_in_code("a@b.com", "123456")


@respx.mock
async def test_codigos_usam_o_endpoint_de_cada_finalidade(neon: NeonAuthIdentity) -> None:
    ok = {"success": True}
    sign_in = respx.post(f"{BASE}/email-otp/send-verification-otp").respond(200, json=ok)
    reset = respx.post(f"{BASE}/email-otp/request-password-reset").respond(200, json=ok)
    await neon.send_code("a@b.com", "sign-in")
    await neon.send_code("a@b.com", "forget-password")
    assert json.loads(sign_in.calls.last.request.content) == {"email": "a@b.com", "type": "sign-in"}
    assert json.loads(reset.calls.last.request.content) == {"email": "a@b.com"}


@respx.mock
async def test_sessao_valida_expirada_e_logout(neon: NeonAuthIdentity) -> None:
    get = respx.get(f"{BASE}/get-session")
    get.respond(200, json={"session": {"id": "s"}, "user": USER})
    identity = await neon.identify("tok.assinado")
    assert identity is not None and identity.user_id == USER["id"]
    assert get.calls.last.request.headers["cookie"] == f"{SESSION_COOKIE}=tok.assinado"
    get.respond(200, content=b"null")
    assert await neon.identify("tok.velho") is None
    respx.post(f"{BASE}/sign-out").respond(401, json={"code": ""})
    await neon.sign_out("tok.velho")  # nunca falha: o cookie local é apagado de todo jeito


@respx.mock
async def test_neon_fora_do_ar_e_erro_de_provedor(neon: NeonAuthIdentity) -> None:
    respx.get(f"{BASE}/get-session").mock(side_effect=httpx.ConnectError("sem rede"))
    with pytest.raises(ProviderError, match="indisponível"):
        await neon.identify("tok")
