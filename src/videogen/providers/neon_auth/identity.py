"""Neon Auth pelo servidor (BFF): o navegador nunca fala com o Neon.

- Senha: `POST /sign-in/email`; código: `POST /email-otp/send-verification-otp` +
  `POST /sign-in/email-otp`; senha nova: `POST /email-otp/reset-password`.
- A sessão é o cookie `__Secure-neon-auth.session_token` devolvido ao servidor; o app guarda o
  token no próprio cookie HttpOnly e o valida em `GET /get-session`.
- Toda chamada leva `Origin` = URL pública do app (precisa estar nos domínios confiáveis).

O magic link do Neon não serve aqui: o link conclui a sessão no domínio do Neon e a troca exige
um cookie de desafio que só o navegador tem (testado em 2026-11-08). O código por e-mail é o
equivalente sem senha que funciona do lado do servidor.
"""

from typing import Any

import httpx

from videogen.core.errors import ProviderError, RateLimited, Unauthorized
from videogen.domain.identity import AuthSession, Identity
from videogen.ports.identity import CodePurpose

SESSION_COOKIE = "__Secure-neon-auth.session_token"
TOO_MANY_REQUESTS = 429
DENIED_STATUSES = frozenset({400, 401, 403})
DENIED_CODES = frozenset({"INVALID_EMAIL_OR_PASSWORD", "INVALID_OTP", "OTP_EXPIRED",
                          "TOO_MANY_ATTEMPTS", "USER_NOT_FOUND", "BANNED_USER"})  # fmt: skip


class NeonAuthIdentity:
    """Implementa `IdentityProvider` e `SessionVerifier`."""

    def __init__(self, base_url: str, origin: str, client: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._origin = origin.rstrip("/")
        self._client = client

    async def sign_in_password(self, email: str, password: str) -> AuthSession:
        response = await self._post("sign-in/email", {"email": email, "password": password})
        return _session(response, "e-mail ou senha inválidos")

    async def send_code(self, email: str, purpose: CodePurpose) -> None:
        if purpose == "forget-password":
            await self._post("email-otp/request-password-reset", {"email": email})
        else:
            await self._post("email-otp/send-verification-otp", {"email": email, "type": purpose})

    async def sign_in_code(self, email: str, code: str) -> AuthSession:
        response = await self._post("sign-in/email-otp", {"email": email, "otp": code})
        return _session(response, "código inválido ou expirado")

    async def reset_password(self, email: str, code: str, new_password: str) -> None:
        payload = {"email": email, "otp": code, "password": new_password}
        await self._post("email-otp/reset-password", payload)

    async def identify(self, token: str) -> Identity | None:
        response = await self._request("GET", "get-session", token=token)
        data = response.json() if response.content else None
        if not isinstance(data, dict) or not isinstance(data.get("user"), dict):
            return None
        return _identity(data["user"])

    async def sign_out(self, token: str) -> None:
        try:
            await self._request("POST", "sign-out", token=token, json={})
        except (Unauthorized, ProviderError):
            pass  # sessão já inválida ou Neon fora do ar: o cookie local é apagado de todo jeito

    async def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        return await self._request("POST", path, json=payload)

    async def _request(
        self, method: str, path: str, *, token: str | None = None, json: Any = None
    ) -> httpx.Response:
        headers = {"Origin": self._origin}
        if token:
            headers["Cookie"] = f"{SESSION_COOKIE}={token}"
        try:
            response = await self._client.request(method, f"{self._base}/{path}",
                                                  headers=headers, json=json)  # fmt: skip
        except httpx.HTTPError as exc:
            raise ProviderError("serviço de login indisponível", retryable=True) from exc
        _raise_for_status(response)
        return response


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    code = _error_code(response)
    if response.status_code == TOO_MANY_REQUESTS:
        raise RateLimited("muitas tentativas; aguarde um minuto e tente de novo")
    if response.status_code in DENIED_STATUSES and (code in DENIED_CODES or code == ""):
        raise Unauthorized("credencial inválida", provider_code=code)
    raise ProviderError("falha no serviço de login", status=response.status_code,
                        provider_code=code, retryable=response.is_server_error)  # fmt: skip


def _error_code(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return ""
    return str(data.get("code", "")) if isinstance(data, dict) else ""


def _session(response: httpx.Response, denied: str) -> AuthSession:
    token = _session_token(response)
    data = response.json()
    user = data.get("user") if isinstance(data, dict) else None
    if not token or not isinstance(user, dict):
        raise Unauthorized(denied)
    return AuthSession(token=token, identity=_identity(user))


def _session_token(response: httpx.Response) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        if name.strip() == SESSION_COOKIE:
            value = rest.split(";", 1)[0].strip()
            return value or None
    return None


def _identity(user: dict[str, Any]) -> Identity:
    try:
        return Identity(user_id=str(user["id"]), email=str(user["email"]).lower(),
                        name=str(user.get("name") or ""))  # fmt: skip
    except (KeyError, ValueError) as exc:
        raise ProviderError("resposta inesperada do serviço de login") from exc
